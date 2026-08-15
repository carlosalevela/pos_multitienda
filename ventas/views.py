from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, F, Sum
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from contabilidad.models import Gasto
from core.permissions import EsAdmin, EsAdminOSupervisor, es_superadmin, get_empresa, scope_qs
from caja.models import SesionCaja
from devoluciones.models import Devolucion, DetalleDevolucion
from productos.models import Inventario, MovimientoInventario
from proveedores.models import Compra
from tiendas.models import Tienda
from usuarios.models import Empleado
from .models import Venta
from .serializers import VentaSerializer, CambioPOSSerializer


# ── Crear venta ───────────────────────────────────────────
class CrearVentaView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        empresa   = get_empresa(request)
        tienda_id = request.data.get("tienda")

        if not es_superadmin(request) and request.user.rol == "cajero":
            if str(request.user.tienda_id) != str(tienda_id):
                return Response(
                    {"error": "No tienes permiso para vender en esta tienda."},
                    status=403)

        sesion = SesionCaja.objects.filter(
            tienda_id=tienda_id,
            tienda__empresa=empresa,
            estado="abierta",
        ).first()

        if not sesion:
            return Response(
                {"error": "No hay caja abierta en esta tienda. Abre la caja primero."},
                status=400)

        data = request.data.copy()
        data["sesion_caja"] = sesion.id

        serializer = VentaSerializer(
            data=data, context={"request": request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        # Agregar cantidades por producto (por si el mismo producto viene
        # en varias líneas) antes de validar stock, evitando falsos positivos.
        qty_por_producto = defaultdict(Decimal)
        for item in request.data.get("detalles", []):
            qty_por_producto[int(item["producto"])] += Decimal(str(item["cantidad"]))

        for producto_id, cantidad_total in qty_por_producto.items():
            try:
                inv = Inventario.objects.select_for_update().select_related(
                    "producto"
                ).get(
                    producto_id=producto_id,
                    tienda_id=tienda_id,
                    tienda__empresa=empresa,
                )
            except Inventario.DoesNotExist:
                return Response(
                    {"error": f"Producto sin inventario en esta tienda (ID {producto_id})."},
                    status=400)

            if inv.stock_actual < cantidad_total:
                return Response({
                    "error": (
                        f"Stock insuficiente para '{inv.producto.nombre}'. "
                        f"Disponible: {inv.stock_actual}, solicitado: {cantidad_total}."
                    )
                }, status=400)

        venta = serializer.save(empleado=request.user)
        empleado_obj = request.user

        for detalle in venta.detalles.all():
            inv = Inventario.objects.select_for_update().get(
                producto=detalle.producto,
                tienda_id=tienda_id,
            )
            inv.stock_actual -= detalle.cantidad
            inv.save()

            MovimientoInventario.objects.create(
                producto=detalle.producto, tienda_id=tienda_id,
                empleado=empleado_obj, tipo="salida",
                cantidad=detalle.cantidad, referencia_tipo="venta",
                referencia_id=venta.id,
                observacion=f"Venta {venta.numero_factura}",
            )

        tier_feedback = None
        if venta.cliente_id:
            from clientes.models import Cliente, TierConfig
            from django.db.models import F
            Cliente.objects.filter(pk=venta.cliente_id).update(
                total_acumulado=F('total_acumulado') + venta.total
            )
            cli = Cliente.objects.get(pk=venta.cliente_id)
            total_acum = float(cli.total_acumulado)
            tier = cli.tier_actual
            siguiente = TierConfig.objects.filter(
                empresa=cli.empresa,
                activo=True,
                umbral_min__gt=total_acum,
            ).order_by("umbral_min").first()
            tier_feedback = {
                "total_acumulado": total_acum,
                "tier_actual": {
                    "nombre":        tier.nombre,
                    "descuento_pct": float(tier.descuento_pct),
                    "color_hex":     tier.color_hex,
                } if tier else None,
                "siguiente_tier": {
                    "nombre":        siguiente.nombre,
                    "umbral_min":    float(siguiente.umbral_min),
                    "descuento_pct": float(siguiente.descuento_pct),
                    "color_hex":     siguiente.color_hex,
                } if siguiente else None,
            }

        return Response({
            "detail":         "Venta registrada correctamente.",
            "numero_factura": venta.numero_factura,
            "total":          float(venta.total),
            "vuelto":         float(venta.vuelto),
            "metodo_pago":    venta.metodo_pago,
            "cliente": (
                f"{venta.cliente.nombre} {venta.cliente.apellido}"
                if venta.cliente else "Consumidor Final"
            ),
            "productos_vendidos": [
                {
                    "producto": d.producto.nombre,
                    "cantidad": float(d.cantidad),
                    "subtotal": float(d.subtotal),
                }
                for d in venta.detalles.all()
            ],
            "tier_feedback": tier_feedback,
        }, status=201)


# ── Listado de ventas ─────────────────────────────────────
class VentaListView(generics.ListAPIView):
    serializer_class   = VentaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs   = Venta.objects.select_related(
            "cliente", "empleado", "tienda", "sesion_caja"
        ).prefetch_related("detalles")

        qs = scope_qs(self.request, qs, campo_empresa="tienda__empresa")

        if user.rol == "cajero":
            qs    = qs.filter(tienda_id=user.tienda_id)
            fecha = self.request.query_params.get("fecha")
            if fecha:
                qs = qs.filter(created_at__date=fecha)
            return qs.order_by("-created_at")

        tienda_id = self.request.query_params.get("tienda_id")
        sesion_id = self.request.query_params.get("sesion_id")
        fecha     = self.request.query_params.get("fecha")
        cliente   = self.request.query_params.get("cliente_id")

        numero_orden = self.request.query_params.get("numero_orden")

        if tienda_id:    qs = qs.filter(tienda_id=tienda_id)
        if sesion_id:    qs = qs.filter(sesion_caja_id=sesion_id)
        if fecha:        qs = qs.filter(created_at__date=fecha)
        if cliente:      qs = qs.filter(cliente_id=cliente)
        if numero_orden: qs = qs.filter(numero_factura__icontains=numero_orden)

        return qs.order_by("-created_at")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context


# ── Detalle de venta ──────────────────────────────────────
class VentaDetailView(generics.RetrieveAPIView):
    serializer_class   = VentaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if es_superadmin(self.request):
            return Venta.objects.prefetch_related("detalles__producto")
        return Venta.objects.filter(
            tienda__empresa=get_empresa(self.request)
        ).prefetch_related("detalles__producto")


# ── Anular venta ──────────────────────────────────────────
class AnularVentaView(APIView):
    permission_classes = [EsAdmin]

    @transaction.atomic
    def post(self, request, pk):
        try:
            qs    = Venta.objects.select_for_update()
            venta = qs.get(pk=pk) if es_superadmin(request) \
                else qs.get(pk=pk, tienda__empresa=get_empresa(request))
        except Venta.DoesNotExist:
            return Response({"error": "Venta no encontrada."}, status=404)

        if venta.estado == "anulada":
            return Response(
                {"error": "Esta venta ya está anulada."}, status=400)

        empleado_obj = request.user
        for detalle in venta.detalles.select_related("producto"):
            Inventario.objects.get_or_create(
                producto=detalle.producto, tienda=venta.tienda,
                defaults={"stock_actual": 0, "stock_minimo": 0, "stock_maximo": 0}
            )
            inv = Inventario.objects.select_for_update().get(
                producto=detalle.producto, tienda=venta.tienda)
            inv.stock_actual += detalle.cantidad
            inv.save(update_fields=["stock_actual"])

            MovimientoInventario.objects.create(
                producto=detalle.producto, tienda=venta.tienda,
                empleado=empleado_obj, tipo="entrada",
                cantidad=detalle.cantidad, referencia_tipo="anulacion",
                referencia_id=venta.id,
                observacion=f"Anulación venta {venta.numero_factura}",
            )

        venta.estado = "anulada"
        venta.save()

        return Response({
            "detail":        f"Venta {venta.numero_factura} anulada. Stock restaurado.",
            "total_anulado": float(venta.total),
        })


# ── Disponibilidad para devolución ────────────────────────
class VentaDisponibleDevolucionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            qs    = Venta.objects.prefetch_related("detalles__producto")
            venta = qs.get(pk=pk) if es_superadmin(request) \
                else qs.get(pk=pk, tienda__empresa=get_empresa(request))
        except Venta.DoesNotExist:
            return Response(
                {"error": "Venta no encontrada."},
                status=status.HTTP_404_NOT_FOUND)

        if venta.estado == "anulada":
            return Response(
                {"error": "La venta está anulada."},
                status=status.HTTP_400_BAD_REQUEST)

        if (request.user.rol in ("supervisor", "cajero")
                and hasattr(request.user, "tienda_id")
                and venta.tienda_id != request.user.tienda_id):
            return Response(
                {"error": "Sin permiso para ver esta venta."},
                status=status.HTTP_403_FORBIDDEN)

        ya_devuelto = {
            dd["producto_id"]: dd["total"]
            for dd in (
                DetalleDevolucion.objects
                .filter(devolucion__venta=venta,
                        devolucion__estado="procesada")
                .values("producto_id")
                .annotate(total=Sum("cantidad"))
            )
        }

        productos = []
        for d in venta.detalles.all():
            devuelto   = ya_devuelto.get(d.producto_id, Decimal("0"))
            disponible = d.cantidad - devuelto
            if disponible > 0:
                productos.append({
                    "producto_id":      d.producto_id,
                    "producto_nombre":  d.producto.nombre,
                    "precio_unitario":  float(d.precio_unitario),
                    "cantidad_vendida": float(d.cantidad),
                    "ya_devuelta":      float(devuelto),
                    "disponible":       float(disponible),
                })

        return Response({
            "venta_id":        venta.id,
            "numero_factura":  venta.numero_factura,
            "fecha":           venta.created_at.date().isoformat(),
            "total":           float(venta.total),
            "productos":       productos,
            "todos_devueltos": len(productos) == 0,
        })


# ── Cambio POS ────────────────────────────────────────────
class CambioPOSView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CambioPOSSerializer(
            data=request.data,
            context={"request": request},
        )
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST)

        venta = serializer.save()

        return Response(
            VentaSerializer(venta, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


# ── Abonar a crédito ──────────────────────────────────────
class AbonarCreditoView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        from .models import PagoVenta
        empresa = get_empresa(request)
        try:
            venta = Venta.objects.select_for_update().get(
                pk=pk, empresa=empresa, a_credito=True)
        except Venta.DoesNotExist:
            return Response({'error': 'Venta a crédito no encontrada.'}, status=404)

        if (not es_superadmin(request) and
                request.user.rol == 'cajero' and
                venta.tienda_id != request.user.tienda_id):
            return Response(
                {'error': 'No tienes permiso para abonar en esta tienda.'},
                status=403)

        if venta.estado == 'anulada':
            return Response({'error': 'La venta está anulada.'}, status=400)

        try:
            monto = Decimal(str(request.data.get('monto', 0)))
        except Exception:
            return Response({'error': 'Monto inválido.'}, status=400)

        metodo = request.data.get('metodo', 'efectivo')
        if metodo not in ('efectivo', 'tarjeta', 'transferencia'):
            return Response({'error': 'Método de pago no válido.'}, status=400)

        saldo = venta.saldo_pendiente
        if monto <= 0:
            return Response({'error': 'El monto debe ser mayor a cero.'}, status=400)
        if monto > saldo:
            return Response(
                {'error': f'El monto supera el saldo pendiente (${saldo:.0f}).'},
                status=400)

        PagoVenta.objects.create(venta=venta, metodo=metodo, monto=monto)

        # Registrar en caja para cuadre: busca la sesión abierta de la tienda
        try:
            from caja.models import SesionCaja, MovimientoCaja
            tienda_id = venta.sesion_caja.tienda_id if venta.sesion_caja_id else None
            if tienda_id:
                sesion_activa = SesionCaja.objects.filter(
                    tienda_id=tienda_id, estado="abierta"
                ).first()
                if sesion_activa:
                    with transaction.atomic():  # savepoint — fallo aquí no revierte el PagoVenta
                        MovimientoCaja.objects.create(
                            sesion=sesion_activa,
                            tipo="abono_credito",
                            metodo_pago=metodo,
                            monto=monto,
                            descripcion=f"Abono crédito {venta.numero_factura}",
                            referencia_id=venta.id,
                            empleado=request.user,
                        )
        except Exception:
            pass  # No bloquear el abono si falla el registro de caja

        # Recargar saldo desde DB para que saldo_pendiente sea exacto
        venta.refresh_from_db()
        venta_fresh = Venta.objects.prefetch_related('pagos').get(pk=venta.pk)
        nuevo_saldo = venta_fresh.saldo_pendiente
        return Response({
            'saldo_anterior':  float(saldo),
            'abono':           float(monto),
            'saldo_pendiente': float(nuevo_saldo),
            'pagado':          nuevo_saldo <= 0,
        })


# ── Cartera (cuentas por cobrar de créditos) ─────────────
class CarteraView(APIView):
    permission_classes = [EsAdminOSupervisor]

    def get(self, request):
        from collections import defaultdict
        empresa   = get_empresa(request)
        tienda_id = request.query_params.get("tienda_id")

        qs = (
            Venta.objects
            .filter(empresa=empresa, a_credito=True, estado="completada")
            .prefetch_related("pagos")
            .select_related("cliente", "tienda")
            .order_by("cliente_id", "-created_at")
        )
        if tienda_id:
            qs = qs.filter(tienda_id=tienda_id)

        cartera: dict = defaultdict(lambda: {
            "cliente_id":      None,
            "cliente_nombre":  "",
            "limite_credito":  Decimal("0"),
            "deuda_total":     Decimal("0"),
            "ventas":          [],
        })

        for v in qs:
            if not v.cliente_id:
                continue
            saldo = v.saldo_pendiente
            if saldo <= Decimal("0"):
                continue
            cid = v.cliente_id
            row = cartera[cid]
            if row["cliente_id"] is None:
                row["cliente_id"]     = v.cliente_id
                row["cliente_nombre"] = f"{v.cliente.nombre} {v.cliente.apellido}"
                row["limite_credito"] = v.cliente.limite_credito
            row["deuda_total"] += saldo
            row["ventas"].append({
                "id":              v.id,
                "numero_factura":  v.numero_factura,
                "total":           float(v.total),
                "saldo_pendiente": float(saldo),
                "fecha":           v.created_at.isoformat(),
                "tienda":          v.tienda.nombre if v.tienda else "",
            })

        result = []
        total_cartera = Decimal("0")
        for data in cartera.values():
            deuda = data["deuda_total"]
            total_cartera += deuda
            result.append({
                "cliente_id":        data["cliente_id"],
                "cliente_nombre":    data["cliente_nombre"],
                "limite_credito":    float(data["limite_credito"]),
                "deuda_total":       float(deuda),
                "credito_disponible": float(data["limite_credito"] - deuda),
                "num_facturas":      len(data["ventas"]),
                "ventas":            data["ventas"],
            })

        result.sort(key=lambda x: x["deuda_total"], reverse=True)
        return Response({
            "total_cartera": float(total_cartera),
            "num_clientes":  len(result),
            "cartera":       result,
        })


# ── Dashboard general Admin ───────────────────────────────
class DashboardAdminView(APIView):
    permission_classes = [EsAdminOSupervisor]

    def get(self, request):
        hoy          = timezone.now().date()
        ayer         = hoy - timedelta(days=1)
        inicio_mes   = timezone.now().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0)
        dia_semana    = timezone.now().weekday()
        inicio_semana = (timezone.now() - timedelta(days=dia_semana)).replace(
            hour=0, minute=0, second=0, microsecond=0)

        periodo        = request.query_params.get("periodo", "mensual")
        inicio_periodo = inicio_semana if periodo == "semanal" else inicio_mes
        tienda_id      = request.query_params.get("tienda_id")

        # ── QuerySets base ─────────────────────────────────
        venta_qs = scope_qs(
            request,
            Venta.objects.filter(estado="completada"),
            campo_empresa="tienda__empresa",
        )
        if tienda_id:
            venta_qs = venta_qs.filter(tienda_id=tienda_id)

        # ── KPI 1: Ventas hoy + variación vs ayer ─────────
        ventas_hoy  = venta_qs.filter(
            created_at__date=hoy).aggregate(t=Sum("total"))["t"] or 0
        ventas_ayer = venta_qs.filter(
            created_at__date=ayer).aggregate(t=Sum("total"))["t"] or 0
        variacion = 0.0
        if ventas_ayer:
            variacion = round(
                ((float(ventas_hoy) - float(ventas_ayer)) / float(ventas_ayer)) * 100, 1)

        # ── KPI 2: Alertas de inventario ──────────────────
        inv_qs = scope_qs(request, Inventario.objects.filter(producto__activo=True))
        if tienda_id:
            inv_qs = inv_qs.filter(tienda_id=tienda_id)
        stock_bajo    = inv_qs.filter(
            stock_actual__lte=F("stock_minimo"), stock_actual__gt=0).count()
        stock_critico = inv_qs.filter(stock_actual__lte=0).count()

        # ── KPI 3: Balance mensual (ventas − gastos) ───────
        ventas_mes = venta_qs.filter(
            created_at__gte=inicio_mes).aggregate(t=Sum("total"))["t"] or 0
        gasto_qs   = scope_qs(request, Gasto.objects.filter(created_at__gte=inicio_mes))
        if tienda_id:
            gasto_qs = gasto_qs.filter(tienda_id=tienda_id)
        gastos_mes      = gasto_qs.aggregate(t=Sum("monto"))["t"] or 0
        balance_mensual = round(float(ventas_mes) - float(gastos_mes), 2)

        # ── KPI 4: Compras pendientes ──────────────────────
        compra_qs = scope_qs(request, Compra.objects.filter(estado="pendiente"))
        if tienda_id:
            compra_qs = compra_qs.filter(tienda_id=tienda_id)
        compras_pendientes = compra_qs.count()

        # ── Gráfico: ventas por tienda ─────────────────────
        ventas_por_tienda = [
            {
                "tienda_id": r["tienda_id"],
                "nombre":    r["tienda__nombre"],
                "total":     float(r["total"] or 0),
            }
            for r in (
                venta_qs.filter(created_at__gte=inicio_periodo)
                .values("tienda_id", "tienda__nombre")
                .annotate(total=Sum("total"))
                .order_by("-total")[:10]
            )
        ]

        # ── Transacciones recientes (ventas + devoluciones) ─
        v_raw = list(
            venta_qs.order_by("-created_at")[:10]
            .values("numero_factura", "tienda__nombre", "total", "created_at")
        )
        dev_qs = scope_qs(request, Devolucion.objects.filter(estado="procesada"))
        if tienda_id:
            dev_qs = dev_qs.filter(tienda_id=tienda_id)
        d_raw = list(
            dev_qs.order_by("-created_at")[:10]
            .values("id", "tienda__nombre", "total_devuelto", "created_at", "tipo")
        )

        transacciones = [
            {
                "tipo":       "venta",
                "numero":     r["numero_factura"],
                "tienda":     r["tienda__nombre"],
                "monto":      float(r["total"]),
                "created_at": r["created_at"].isoformat(),
            }
            for r in v_raw
        ] + [
            {
                "tipo":       r["tipo"],
                "numero":     f"DEV-{r['id']}",
                "tienda":     r["tienda__nombre"],
                "monto":      -float(r["total_devuelto"]),
                "created_at": r["created_at"].isoformat(),
            }
            for r in d_raw
        ]
        transacciones.sort(key=lambda x: x["created_at"], reverse=True)
        transacciones = transacciones[:15]

        # ── Desempeño por tienda ───────────────────────────
        tienda_qs = scope_qs(
            request,
            Tienda.objects.filter(activo=True),
            campo_empresa="empresa",
        )
        if tienda_id:
            tienda_qs = tienda_qs.filter(id=tienda_id)

        desempeno = []
        for t in tienda_qs:
            v_hoy = Venta.objects.filter(
                tienda=t, estado="completada",
                created_at__date=hoy,
            ).aggregate(total=Sum("total"))["total"] or 0

            cajas_abiertas = SesionCaja.objects.filter(
                tienda=t, estado="abierta").count()
            cajas_hoy   = SesionCaja.objects.filter(
                tienda=t, fecha_apertura__date=hoy).count()
            cajas_total = max(cajas_hoy, cajas_abiertas, 1)
            eficiencia  = round((cajas_abiertas / cajas_total) * 100)

            encargado = Empleado.objects.filter(
                tienda=t, rol__in=["admin", "supervisor"], activo=True,
            ).first()
            nombre_enc = (
                f"{encargado.nombre} {encargado.apellido}"
                if encargado else "—"
            )

            estado = (
                "optimo"   if eficiencia >= 90
                else "estable"  if eficiencia >= 60
                else "moderado"
            )

            desempeno.append({
                "tienda_id":      t.id,
                "nombre":         t.nombre,
                "encargado":      nombre_enc,
                "ventas_hoy":     float(v_hoy),
                "cajas_activas":  cajas_abiertas,
                "cajas_total":    cajas_total,
                "eficiencia_pct": eficiencia,
                "estado":         estado,
            })

        desempeno.sort(key=lambda x: x["ventas_hoy"], reverse=True)

        # ── Desglose por método de pago (período) ─────────
        metodos_raw = (
            venta_qs.filter(created_at__gte=inicio_periodo)
            .values("metodo_pago")
            .annotate(total=Sum("total"), count=Count("id"))
            .order_by("-total")
        )
        metodos_pago = [
            {
                "metodo": r["metodo_pago"],
                "total":  float(r["total"] or 0),
                "count":  r["count"],
            }
            for r in metodos_raw
        ]

        return Response({
            "kpis": {
                "ventas_hoy":               float(ventas_hoy),
                "ventas_hoy_variacion_pct": variacion,
                "inventario_bajo_sku":      stock_bajo,
                "alertas_criticas":         stock_critico,
                "balance_mensual":          balance_mensual,
                "compras_pendientes":       compras_pendientes,
            },
            "periodo":                periodo,
            "ventas_por_tienda":       ventas_por_tienda,
            "transacciones_recientes": transacciones,
            "desempeno_tiendas":       desempeno,
            "metodos_pago":            metodos_pago,
        })
