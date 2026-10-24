from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from caja.models import SesionCaja, MovimientoCaja
from core.permissions import EsAdminOSupervisor, es_superadmin, get_empresa, scope_qs
from productos.models import Inventario, MovimientoInventario, Producto
from .models import Cliente, Separado, AbonoSeparado, DetalleSeparado, TierConfig
from .serializers import ClienteSerializer, ClienteSimpleSerializer, SeparadoSerializer, TierConfigSerializer


# ── Helper empleado ───────────────────────────────────────
def _get_empleado(request):
    return request.user


# ── Clientes ──────────────────────────────────────────────
class ClienteListCreateView(generics.ListCreateAPIView):
    serializer_class   = ClienteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = scope_qs(
            self.request,
            Cliente.objects.filter(activo=True),
            campo_empresa="empresa",
        )

        tienda_id = self.request.query_params.get("tienda_id")
        if tienda_id:
            qs = qs.filter(tienda_id=tienda_id)

        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(nombre__icontains=q)     |
                Q(apellido__icontains=q)   |
                Q(cedula_nit__icontains=q) |
                Q(telefono__icontains=q)
            )
        return qs.order_by("nombre")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if not es_superadmin(self.request):
            empresa = get_empresa(self.request)
            if empresa:
                context['tier_configs'] = list(
                    TierConfig.objects.filter(empresa=empresa, activo=True)
                    .order_by('-umbral_min')
                )
        return context

    def perform_create(self, serializer):
        if es_superadmin(self.request):
            serializer.save()
        else:
            tienda_id = self.request.data.get("tienda")
            serializer.save(
                empresa   = get_empresa(self.request),
                tienda_id = tienda_id if tienda_id else None,
            )


class ClienteDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class   = ClienteSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [EsAdminOSupervisor()]
        return [IsAuthenticated()]

    def get_queryset(self):
        if es_superadmin(self.request):
            return Cliente.objects.all()
        return Cliente.objects.filter(
            empresa=get_empresa(self.request))

    def destroy(self, request, *args, **kwargs):
        cliente = self.get_object()
        cliente.activo = False
        cliente.save()
        return Response(
            {"detail": f"Cliente '{cliente.nombre}' desactivado."})


class ClienteSimpleListView(generics.ListAPIView):
    serializer_class   = ClienteSimpleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = scope_qs(
            self.request,
            Cliente.objects.filter(activo=True),
            campo_empresa="empresa",
        )
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(nombre__icontains=q) | Q(cedula_nit__icontains=q))
        return qs.order_by("nombre")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if not es_superadmin(self.request):
            empresa = get_empresa(self.request)
            if empresa:
                context['tier_configs'] = list(
                    TierConfig.objects.filter(empresa=empresa, activo=True)
                    .order_by('-umbral_min')
                )
        return context


# ── Separados ─────────────────────────────────────────────
class SeparadoListCreateView(generics.ListCreateAPIView):
    serializer_class   = SeparadoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = scope_qs(
            self.request,
            Separado.objects.select_related(
                "cliente", "tienda", "empleado"
            ).prefetch_related("detalles", "abonos"),
        )

        tienda_id      = self.request.query_params.get("tienda_id")
        estado         = self.request.query_params.get("estado")
        cliente        = self.request.query_params.get("cliente_id")
        fecha_creacion = self.request.query_params.get("fecha_creacion")

        if self.request.user.rol == "cajero":
            qs = qs.filter(tienda_id=self.request.user.tienda_id)
        elif tienda_id:
            qs = qs.filter(tienda_id=tienda_id)

        if estado:         qs = qs.filter(estado=estado)
        if cliente:        qs = qs.filter(cliente_id=cliente)
        if fecha_creacion: qs = qs.filter(created_at__date=fecha_creacion)

        return qs.order_by("-created_at")

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tienda   = serializer.validated_data['tienda']
        detalles = serializer.validated_data['detalles']

        # ── Validar y reservar stock ───────────────────────
        inv_reservas = []
        for det in detalles:
            try:
                inv = Inventario.objects.select_for_update().get(
                    producto=det['producto'], tienda=tienda)
            except Inventario.DoesNotExist:
                raise ValidationError({
                    "error": (
                        f"'{det['producto'].nombre}' no tiene inventario "
                        f"registrado en esta tienda."
                    )
                })
            if inv.stock_actual < det['cantidad']:
                raise ValidationError({
                    "error": (
                        f"Stock insuficiente para '{det['producto'].nombre}'. "
                        f"Disponible: {inv.stock_actual}, solicitado: {det['cantidad']}."
                    )
                })
            inv_reservas.append((inv, det))

        separado = serializer.save(empleado=_get_empleado(request))

        # ── Decrementar stock (reserva física) ────────────
        for inv, det in inv_reservas:
            inv.stock_actual -= det['cantidad']
            inv.save(update_fields=['stock_actual'])
            MovimientoInventario.objects.create(
                producto        = det['producto'],
                tienda          = tienda,
                empleado        = _get_empleado(request),
                tipo            = 'salida',
                cantidad        = det['cantidad'],
                referencia_tipo = 'separado',
                referencia_id   = separado.id,
                observacion     = (
                    f"Separado #{separado.id} — "
                    f"{separado.cliente.nombre} {separado.cliente.apellido}"
                ),
            )

        # ── Abono inicial opcional ────────────────────────
        abono_inicial     = request.data.get('abono_inicial')
        metodo_pago       = request.data.get('metodo_pago', 'efectivo')
        cuenta_destino_id = request.data.get('cuenta_destino')
        en_caja           = False

        if abono_inicial:
            try:
                monto = Decimal(str(abono_inicial))
            except InvalidOperation:
                raise ValidationError(
                    {"abono_inicial": "El monto del abono inicial no es válido."})

            if monto > 0:
                if monto > separado.saldo_pendiente:
                    raise ValidationError(
                        {"abono_inicial": "El abono inicial no puede "
                                          "superar el total del separado."})

                AbonoSeparado.objects.create(
                    separado    = separado,
                    empleado    = _get_empleado(request),
                    monto       = monto,
                    metodo_pago = metodo_pago,
                )

                separado.abono_acumulado += monto
                separado.saldo_pendiente -= monto

                if separado.saldo_pendiente <= 0:
                    separado.estado          = 'pagado'
                    separado.saldo_pendiente = Decimal('0')

                separado.save()

                sesion = SesionCaja.objects.filter(
                    tienda_id=separado.tienda_id, estado='abierta').first()
                if sesion:
                    MovimientoCaja.objects.create(
                        sesion             = sesion,
                        tipo               = 'abono_separado',
                        metodo_pago        = metodo_pago,
                        monto              = monto,
                        referencia_id      = separado.id,
                        empleado           = _get_empleado(request),
                        cuenta_bancaria_id = cuenta_destino_id or None,
                        descripcion        = (
                            f"Abono inicial separado #{separado.id} - "
                            f"{separado.cliente.nombre} "
                            f"{separado.cliente.apellido}"
                        ),
                    )
                    en_caja = True

        headers = self.get_success_headers(serializer.data)
        return Response(
            {**serializer.data, "en_caja": en_caja},
            status=201,
            headers=headers,
        )


class SeparadoDetailView(generics.RetrieveAPIView):
    serializer_class   = SeparadoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if es_superadmin(self.request):
            return Separado.objects.prefetch_related(
                "detalles__producto", "abonos__empleado")
        return Separado.objects.filter(
            tienda__empresa=get_empresa(self.request)
        ).prefetch_related("detalles__producto", "abonos__empleado")


# ── Abonar separado ───────────────────────────────────────
class AbonarSeparadoView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        try:
            filtro = {"pk": pk}
            if not es_superadmin(request):
                filtro["tienda__empresa"] = get_empresa(request)
            separado = Separado.objects.select_for_update().get(**filtro)
        except Separado.DoesNotExist:
            return Response(
                {"error": "Separado no encontrado."}, status=404)

        if separado.estado != "activo":
            return Response(
                {"error": f"Este separado está {separado.estado}."},
                status=400)

        monto_raw = request.data.get("monto")
        try:
            monto = Decimal(str(monto_raw))
        except (InvalidOperation, TypeError):
            return Response({"error": "El monto debe ser un número válido."}, status=400)
        if monto <= 0:
            return Response({"error": "El monto debe ser mayor a 0."}, status=400)
        metodo_pago       = request.data.get("metodo_pago", "efectivo")
        cuenta_destino_id = request.data.get("cuenta_destino")

        if monto > separado.saldo_pendiente:
            return Response(
                {"error": f"Excede el saldo pendiente de "
                          f"${separado.saldo_pendiente}."},
                status=400)

        AbonoSeparado.objects.create(
            separado    = separado,
            empleado    = _get_empleado(request),
            monto       = monto,
            metodo_pago = metodo_pago,
        )

        separado.abono_acumulado += monto
        separado.saldo_pendiente -= monto

        if separado.saldo_pendiente <= 0:
            separado.estado          = "pagado"
            separado.saldo_pendiente = Decimal("0")

        separado.save()

        sesion = SesionCaja.objects.filter(
            tienda_id=separado.tienda_id,
            estado="abierta",
        ).first()

        if sesion:
            MovimientoCaja.objects.create(
                sesion             = sesion,
                tipo               = "abono_separado",
                metodo_pago        = metodo_pago,
                monto              = monto,
                referencia_id      = separado.id,
                empleado           = _get_empleado(request),
                cuenta_bancaria_id = cuenta_destino_id or None,
                descripcion        = (
                    f"Abono separado #{separado.id} - "
                    f"{separado.cliente.nombre} "
                    f"{separado.cliente.apellido}"
                ),
            )

        return Response({
            "detail":          "Abono registrado correctamente.",
            "abono":           float(monto),
            "abono_acumulado": float(separado.abono_acumulado),
            "saldo_pendiente": float(separado.saldo_pendiente),
            "estado":          separado.estado,
            "en_caja":         sesion is not None,
        })


# ── Cancelar separado ─────────────────────────────────────
class CancelarSeparadoView(APIView):
    permission_classes = [EsAdminOSupervisor]

    @transaction.atomic
    def post(self, request, pk):
        try:
            filtro = {"pk": pk}
            if not es_superadmin(request):
                filtro["tienda__empresa"] = get_empresa(request)
            # select_for_update en el separado para evitar doble cancelación concurrente
            separado = Separado.objects.select_for_update().prefetch_related(
                "detalles__producto"
            ).get(**filtro)
        except Separado.DoesNotExist:
            return Response(
                {"error": "Separado no encontrado."}, status=404)

        if separado.estado == "pagado":
            return Response(
                {"error": "No se puede cancelar un separado ya pagado."},
                status=400)
        if separado.estado == "cancelado":
            return Response(
                {"error": "Este separado ya está cancelado."},
                status=400)

        # Restaurar stock reservado al crear el separado
        for detalle in separado.detalles.all():
            inv, _ = Inventario.objects.select_for_update().get_or_create(
                producto = detalle.producto,
                tienda   = separado.tienda,
                defaults = {"stock_actual": 0, "stock_minimo": 0, "stock_maximo": 0},
            )
            inv.stock_actual += detalle.cantidad
            inv.save(update_fields=["stock_actual"])

            MovimientoInventario.objects.create(
                producto        = detalle.producto,
                tienda          = separado.tienda,
                empleado        = _get_empleado(request),
                tipo            = "entrada",
                cantidad        = detalle.cantidad,
                referencia_tipo = "cancelacion_separado",
                referencia_id   = separado.id,
                observacion     = f"Cancelación separado #{separado.id}",
            )

        # Registrar reversión en caja por método de pago real (no hardcoded)
        if separado.abono_acumulado > 0:
            sesion = SesionCaja.objects.filter(
                tienda_id=separado.tienda_id, estado="abierta").first()
            if sesion:
                abonos_por_metodo = (
                    AbonoSeparado.objects
                    .filter(separado=separado)
                    .values("metodo_pago")
                    .annotate(total=Sum("monto"))
                )
                for row in abonos_por_metodo:
                    MovimientoCaja.objects.create(
                        sesion        = sesion,
                        tipo          = "cancelacion_separado",
                        metodo_pago   = row["metodo_pago"],
                        monto         = row["total"],
                        referencia_id = separado.id,
                        empleado      = _get_empleado(request),
                        descripcion   = (
                            f"Reversión separado #{separado.id} - "
                            f"{separado.cliente.nombre} "
                            f"{separado.cliente.apellido}"
                        ),
                    )

        separado.estado = "cancelado"
        separado.save()

        return Response({
            "detail": f"Separado #{separado.id} cancelado. Stock restaurado.",
            "productos_restaurados": [
                {"producto": d.producto.nombre, "cantidad": float(d.cantidad)}
                for d in separado.detalles.all()
            ],
        })


# ── Cambiar producto de un separado activo ────────────────
class CambiarProductoSeparadoView(APIView):
    permission_classes = [EsAdminOSupervisor]

    @transaction.atomic
    def post(self, request, pk):
        filtro = {"pk": pk}
        if not es_superadmin(request):
            filtro["tienda__empresa"] = get_empresa(request)
        try:
            separado = Separado.objects.select_for_update().prefetch_related(
                "detalles__producto"
            ).get(**filtro)
        except Separado.DoesNotExist:
            return Response({"error": "Separado no encontrado."}, status=404)

        if separado.estado != "activo":
            return Response(
                {"error": f"Este separado está {separado.estado} y no se puede modificar."},
                status=400)

        detalle_id        = request.data.get("detalle_id")
        nuevo_producto_id = request.data.get("nuevo_producto_id")

        if not detalle_id or not nuevo_producto_id:
            return Response(
                {"error": "detalle_id y nuevo_producto_id son requeridos."}, status=400)

        try:
            detalle = separado.detalles.get(pk=detalle_id)
        except DetalleSeparado.DoesNotExist:
            return Response(
                {"error": "Detalle no encontrado en este separado."}, status=404)

        try:
            nuevo_producto = Producto.objects.get(pk=nuevo_producto_id)
        except Producto.DoesNotExist:
            return Response({"error": "Producto no encontrado."}, status=404)

        try:
            nueva_cantidad = Decimal(str(
                request.data.get("nueva_cantidad", detalle.cantidad)))
            nuevo_precio   = Decimal(str(
                request.data.get("nuevo_precio_unitario", nuevo_producto.precio)))
        except (InvalidOperation, TypeError):
            return Response(
                {"error": "Cantidad o precio inválido."}, status=400)

        if nueva_cantidad <= 0:
            return Response(
                {"error": "La cantidad debe ser mayor a cero."}, status=400)

        # ── Restaurar stock del producto anterior ─────────
        old_inv, _ = Inventario.objects.select_for_update().get_or_create(
            producto = detalle.producto,
            tienda   = separado.tienda,
            defaults = {"stock_actual": 0, "stock_minimo": 0, "stock_maximo": 0},
        )
        old_inv.stock_actual += detalle.cantidad
        old_inv.save(update_fields=["stock_actual"])

        MovimientoInventario.objects.create(
            producto        = detalle.producto,
            tienda          = separado.tienda,
            empleado        = _get_empleado(request),
            tipo            = "entrada",
            cantidad        = detalle.cantidad,
            referencia_tipo = "cambio_separado",
            referencia_id   = separado.id,
            observacion     = (
                f"Cambio separado #{separado.id} — "
                f"restaurando '{detalle.producto.nombre}'"
            ),
        )

        # ── Validar y reservar stock del nuevo producto ───
        try:
            new_inv = Inventario.objects.select_for_update().get(
                producto = nuevo_producto, tienda = separado.tienda)
        except Inventario.DoesNotExist:
            return Response({
                "error": (
                    f"'{nuevo_producto.nombre}' no tiene inventario "
                    f"registrado en esta tienda."
                )
            }, status=400)

        if new_inv.stock_actual < nueva_cantidad:
            return Response({
                "error": (
                    f"Stock insuficiente para '{nuevo_producto.nombre}'. "
                    f"Disponible: {new_inv.stock_actual}, "
                    f"requerido: {nueva_cantidad}."
                )
            }, status=400)

        new_inv.stock_actual -= nueva_cantidad
        new_inv.save(update_fields=["stock_actual"])

        MovimientoInventario.objects.create(
            producto        = nuevo_producto,
            tienda          = separado.tienda,
            empleado        = _get_empleado(request),
            tipo            = "salida",
            cantidad        = nueva_cantidad,
            referencia_tipo = "cambio_separado",
            referencia_id   = separado.id,
            observacion     = (
                f"Cambio separado #{separado.id} — "
                f"reservando '{nuevo_producto.nombre}'"
            ),
        )

        # ── Actualizar detalle ────────────────────────────
        old_subtotal   = detalle.subtotal
        nuevo_subtotal = nueva_cantidad * nuevo_precio

        detalle.producto        = nuevo_producto
        detalle.cantidad        = nueva_cantidad
        detalle.precio_unitario = nuevo_precio
        detalle.subtotal        = nuevo_subtotal
        detalle.save()

        # ── Recalcular totales del separado ───────────────
        diff = nuevo_subtotal - old_subtotal
        separado.total          += diff
        separado.saldo_pendiente = max(
            Decimal("0"),
            separado.total - separado.abono_acumulado,
        )
        separado.save()

        return Response({
            "detail": (
                f"Producto cambiado a '{nuevo_producto.nombre}' "
                f"×{nueva_cantidad}."
            ),
            "total":              float(separado.total),
            "saldo_pendiente":    float(separado.saldo_pendiente),
            "abono_acumulado":    float(separado.abono_acumulado),
            "detalle_id":         detalle.pk,
            "nuevo_producto_id":  nuevo_producto.id,
            "nuevo_producto_nombre": nuevo_producto.nombre,
            "nueva_cantidad":     float(nueva_cantidad),
            "nuevo_precio":       float(nuevo_precio),
            "nuevo_subtotal":     float(nuevo_subtotal),
        })


# ── Resumen de cliente (para POS y separados) ─────────────
class ClienteResumenView(APIView):
    """
    GET /api/clientes/{pk}/resumen/
    Devuelve info básica del cliente + conteo de separados activos.
    Útil para el badge 'X apartados pendientes' en POS y separados.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        filtro = {"pk": pk}
        if not es_superadmin(request):
            filtro["empresa"] = get_empresa(request)
        try:
            cliente = Cliente.objects.get(**filtro)
        except Cliente.DoesNotExist:
            return Response({"error": "Cliente no encontrado."}, status=404)

        separados_qs = Separado.objects.filter(cliente=cliente)
        activos      = separados_qs.filter(estado="activo")

        deuda_total = activos.aggregate(
            t=Sum("saldo_pendiente"))["t"] or Decimal("0")

        ultimo = separados_qs.order_by("-created_at").first()

        return Response({
            "id":               cliente.id,
            "nombre":           f"{cliente.nombre} {cliente.apellido}",
            "cedula_nit":       cliente.cedula_nit,
            "telefono":         cliente.telefono,
            "separados_activos":  activos.count(),
            "deuda_total":      float(deuda_total),
            "ultimo_separado":  {
                "id":              ultimo.id,
                "total":           float(ultimo.total),
                "saldo_pendiente": float(ultimo.saldo_pendiente),
                "estado":          ultimo.estado,
                "fecha_limite":    str(ultimo.fecha_limite) if ultimo.fecha_limite else None,
                "created_at":      str(ultimo.created_at),
            } if ultimo else None,
        })


# ── Alertas de separados ──────────────────────────────────
class AlertasSeparadosView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        hoy     = timezone.localdate()
        en3dias = hoy + timedelta(days=3)

        qs = scope_qs(
            request,
            Separado.objects.filter(
                estado='activo',
                fecha_limite__isnull=False,
            ).select_related('cliente', 'tienda'),
        )

        if request.user.rol == 'cajero':
            qs = qs.filter(tienda_id=request.user.tienda_id)
        else:
            tienda_id = request.query_params.get('tienda_id')
            if tienda_id:
                qs = qs.filter(tienda_id=tienda_id)

        vencidos   = qs.filter(fecha_limite__lt=hoy)
        por_vencer = qs.filter(
            fecha_limite__gte=hoy, fecha_limite__lte=en3dias)

        def serializar(sep):
            return {
                'id':              sep.id,
                'cliente':         f"{sep.cliente.nombre} "
                                   f"{sep.cliente.apellido}",
                'tienda':          sep.tienda.nombre,
                'saldo_pendiente': float(sep.saldo_pendiente),
                'fecha_limite':    str(sep.fecha_limite),
                'dias_restantes':  (sep.fecha_limite - hoy).days,
            }

        return Response({
            'vencidos':      [serializar(s) for s in vencidos],
            'por_vencer':    [serializar(s) for s in por_vencer],
            'total_alertas': vencidos.count() + por_vencer.count(),
        })


# ── Créditos de un cliente ────────────────────────────────
class CreditosClienteView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from ventas.models import Venta
        empresa = get_empresa(request)
        if empresa:
            cliente = Cliente.objects.filter(pk=pk, empresa=empresa).first()
        else:
            cliente = Cliente.objects.filter(pk=pk).first()
        if not cliente:
            return Response({'error': 'Cliente no encontrado.'}, status=404)

        filtro_empresa = {'empresa': empresa} if empresa else {}
        ventas_qs = Venta.objects.filter(
            cliente=cliente, a_credito=True, estado='completada', **filtro_empresa
        ).prefetch_related('pagos').order_by('-created_at')

        ventas_data = []
        deuda_total = Decimal('0')
        for v in ventas_qs:
            saldo = v.saldo_pendiente
            deuda_total += max(saldo, Decimal('0'))
            ventas_data.append({
                'id':               v.id,
                'numero_factura':   v.numero_factura,
                'total':            float(v.total),
                'total_pagado':     float(v.total_pagado),
                'saldo_pendiente':  float(max(saldo, Decimal('0'))),
                'fecha':            v.created_at.isoformat(),
                'estado_credito':   'pagado' if saldo <= 0 else 'pendiente',
            })

        return Response({
            'cliente_id':        cliente.id,
            'limite_credito':    float(cliente.limite_credito),
            'deuda_total':       float(deuda_total),
            'credito_disponible': float(cliente.limite_credito - deuda_total),
            'ventas':            ventas_data,
        })


# ── Abonos por fecha ──────────────────────────────────────
class AbonosPorFechaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        fecha     = request.query_params.get("fecha")
        tienda_id = request.query_params.get("tienda_id")

        if not fecha:
            return Response(
                {"error": "Parámetro 'fecha' requerido."}, status=400)

        qs = scope_qs(
            request,
            AbonoSeparado.objects.select_related("separado__cliente", "empleado"),
            campo_empresa="separado__tienda__empresa",
        )

        qs = qs.filter(created_at__date=fecha)

        if request.user.rol == "cajero":
            qs = qs.filter(
                separado__tienda_id=request.user.tienda_id)
        elif tienda_id:
            qs = qs.filter(separado__tienda_id=tienda_id)

        data = [{
            "id":              a.id,
            "separado_id":     a.separado_id,
            "cliente_nombre":  f"{a.separado.cliente.nombre} "
                               f"{a.separado.cliente.apellido}",
            "empleado_nombre": (
                f"{a.empleado.nombre} {a.empleado.apellido}"
                if a.empleado else ""
            ),
            "monto":           float(a.monto),
            "metodo_pago":     a.metodo_pago,
            "created_at":      str(a.created_at),
        } for a in qs]

        return Response({
            "abonos": data,
            "total":  sum(d["monto"] for d in data),
        })


# ── Recordatorios WhatsApp de separados ──────────────────
class RecordatoriosSeparadosView(APIView):
    """
    POST /api/clientes/separados/recordatorios/?dias=3&tienda_id=X
    Solo admin/supervisor. Envía WhatsApp a clientes con separados
    activos que vencen en los próximos `dias` días.
    """
    permission_classes = [EsAdminOSupervisor]

    def post(self, request):
        dias = int(request.query_params.get("dias", 3))
        tienda_id = request.query_params.get("tienda_id")

        hoy     = timezone.localdate()
        limite  = hoy + timedelta(days=dias)

        qs = scope_qs(
            request,
            Separado.objects.filter(
                estado="activo",
                fecha_limite__isnull=False,
                fecha_limite__gte=hoy,
                fecha_limite__lte=limite,
            ).select_related("cliente", "tienda"),
        )

        if tienda_id:
            qs = qs.filter(tienda_id=tienda_id)

        empresa = get_empresa(request)
        if not empresa:
            return Response({"error": "No se pudo determinar la empresa."}, status=400)

        separados_data = []
        for sep in qs:
            separados_data.append({
                "separado_id":    sep.id,
                "cliente_nombre": f"{sep.cliente.nombre} {sep.cliente.apellido}".strip(),
                "tienda_nombre":  sep.tienda.nombre,
                "fecha_limite":   sep.fecha_limite.strftime("%d/%m/%Y"),
                "saldo_pendiente": f"{int(sep.saldo_pendiente):,}".replace(",", "."),
                "telefono":       sep.cliente.telefono,
            })

        if not separados_data:
            return Response({
                "enviados":      0,
                "sin_telefono":  [],
                "errores":       [],
                "mensaje":       f"No hay separados que venzan en los próximos {dias} días.",
            })

        from configuracion.whatsapp_service import enviar_recordatorio_separado
        resultado = enviar_recordatorio_separado(
            empresa_id=empresa.id,
            tienda_id=int(tienda_id) if tienda_id else None,
            separados=separados_data,
        )
        resultado["total_encontrados"] = len(separados_data)
        return Response(resultado)


# ── Tiers de fidelización ─────────────────────────────────
def _get_empresa_tier(request):
    """Para superadmin requiere ?empresa=ID; para el resto usa su empresa."""
    if es_superadmin(request):
        from empresas.models import Empresa
        empresa_id = request.query_params.get("empresa") or request.data.get("empresa")
        if not empresa_id:
            return None
        return Empresa.objects.filter(pk=empresa_id).first()
    return get_empresa(request)


class TierConfigListCreateView(generics.ListCreateAPIView):
    serializer_class   = TierConfigSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        empresa = _get_empresa_tier(self.request)
        if empresa is None:
            return TierConfig.objects.none()
        return TierConfig.objects.filter(empresa=empresa)

    def perform_create(self, serializer):
        empresa = _get_empresa_tier(self.request)
        if empresa is None:
            raise ValidationError({"empresa": "Se requiere ?empresa=ID para superadmin."})
        serializer.save(empresa=empresa)


class TierConfigDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class   = TierConfigSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        empresa = _get_empresa_tier(self.request)
        if empresa is None:
            return TierConfig.objects.none()
        return TierConfig.objects.filter(empresa=empresa)