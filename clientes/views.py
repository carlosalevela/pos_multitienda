from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.db.models import Q
from decimal import Decimal
from productos.models import Inventario, MovimientoInventario
from django.utils import timezone
from datetime import timedelta

from .models import Cliente, Separado, AbonoSeparado
from .serializers import (
    ClienteSerializer, ClienteSimpleSerializer,
    SeparadoSerializer,
)


# ── Permisos ───────────────────────────────────────────────────
class EsAdminOSupervisor(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) \
               and request.user.rol in ["admin", "supervisor"]


# ── Clientes ──────────────────────────────────────────────────
class ClienteListCreateView(generics.ListCreateAPIView):
    serializer_class   = ClienteSerializer
    permission_classes = [IsAuthenticated]  # ✅ todos pueden listar y crear

    def get_queryset(self):
        qs = Cliente.objects.filter(activo=True).order_by("nombre")
        q  = self.request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(nombre__icontains=q)     |
                Q(apellido__icontains=q)   |
                Q(cedula_nit__icontains=q) |
                Q(telefono__icontains=q)
            )
        return qs


class ClienteDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset         = Cliente.objects.all()
    serializer_class = ClienteSerializer

    # ✅ GET → cualquier autenticado | PUT/PATCH/DELETE → solo admin o supervisor
    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [EsAdminOSupervisor()]
        return [IsAuthenticated()]

    def destroy(self, request, *args, **kwargs):
        cliente = self.get_object()
        cliente.activo = False
        cliente.save()
        return Response({"detail": f"Cliente '{cliente.nombre}' desactivado."})


class ClienteSimpleListView(generics.ListAPIView):
    serializer_class   = ClienteSimpleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Cliente.objects.filter(activo=True).order_by("nombre")
        q  = self.request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(nombre__icontains=q) | Q(cedula_nit__icontains=q)
            )
        return qs


# ── Separados ─────────────────────────────────────────────────
class SeparadoListCreateView(generics.ListCreateAPIView):
    serializer_class   = SeparadoSerializer
    permission_classes = [IsAuthenticated]  # ✅ cajero puede crear separados

    def get_queryset(self):
        qs = Separado.objects.select_related(
        "cliente", "tienda", "empleado"
    ).prefetch_related("detalles", "abonos")

        tienda_id      = self.request.query_params.get("tienda_id")
        estado         = self.request.query_params.get("estado")
        cliente        = self.request.query_params.get("cliente_id")
        fecha_creacion = self.request.query_params.get("fecha_creacion")  # ✅ nuevo

        if self.request.user.rol == "cajero":
            qs = qs.filter(tienda_id=self.request.user.tienda_id)
        elif tienda_id:
            qs = qs.filter(tienda_id=tienda_id)

        if estado:          qs = qs.filter(estado=estado)
        if cliente:         qs = qs.filter(cliente_id=cliente)
        if fecha_creacion:  qs = qs.filter(created_at__date=fecha_creacion)  # ✅ nuevo

        return qs.order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(empleado=self.request.user)


class SeparadoDetailView(generics.RetrieveAPIView):
    queryset           = Separado.objects.prefetch_related(
                             "detalles__producto", "abonos__empleado")
    serializer_class   = SeparadoSerializer
    permission_classes = [IsAuthenticated]


class AbonarSeparadoView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        try:
            separado = Separado.objects.select_for_update().get(pk=pk)
        except Separado.DoesNotExist:
            return Response({"error": "Separado no encontrado."}, status=404)

        if separado.estado != "activo":
            return Response(
                {"error": f"Este separado está {separado.estado}."},
                status=400)

        monto = request.data.get("monto")
        if not monto or float(monto) <= 0:
            return Response(
                {"error": "El monto debe ser mayor a 0."}, status=400)

        monto       = Decimal(str(monto))
        metodo_pago = request.data.get("metodo_pago", "efectivo")

        if monto > Decimal(str(separado.saldo_pendiente)):
            return Response(
                {"error": f"Excede el saldo pendiente de ${separado.saldo_pendiente}."},
                status=400)

        AbonoSeparado.objects.create(
            separado    = separado,
            empleado    = request.user,
            monto       = monto,
            metodo_pago = metodo_pago,
        )

        separado.abono_acumulado += monto
        separado.saldo_pendiente -= monto

        if separado.saldo_pendiente <= 0:
            separado.estado          = "pagado"
            separado.saldo_pendiente = Decimal("0")

        separado.save()

        # ✅ Registrar en caja si hay sesión abierta
        from caja.models import SesionCaja, MovimientoCaja
        sesion = SesionCaja.objects.filter(
            tienda_id=separado.tienda_id,
            estado="abierta"
        ).first()

        if sesion:
            MovimientoCaja.objects.create(
                sesion        = sesion,
                tipo          = "abono_separado",
                metodo_pago   = metodo_pago,
                monto         = monto,
                referencia_id = separado.id,
                empleado      = request.user,
                descripcion   = (
                    f"Abono separado #{separado.id} - "
                    f"{separado.cliente.nombre} {separado.cliente.apellido}"
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


class CancelarSeparadoView(APIView):
    permission_classes = [EsAdminOSupervisor]  # ✅ cajero NO puede cancelar

    @transaction.atomic
    def post(self, request, pk):
        try:
            separado = Separado.objects.prefetch_related(
                "detalles__producto"
            ).get(pk=pk)
        except Separado.DoesNotExist:
            return Response({"error": "Separado no encontrado."}, status=404)

        if separado.estado == "pagado":
            return Response(
                {"error": "No se puede cancelar un separado ya pagado."},
                status=400
            )

        if separado.estado == "cancelado":
            return Response(
                {"error": "Este separado ya está cancelado."},
                status=400
            )

        # ✅ Restaurar stock por cada detalle
        for detalle in separado.detalles.all():
            inv, _ = Inventario.objects.select_for_update().get_or_create(
                producto = detalle.producto,
                tienda   = separado.tienda,
                defaults = {
                    "stock_actual": 0,
                    "stock_minimo": 0,
                    "stock_maximo": 0,
                }
            )
            inv.stock_actual += detalle.cantidad
            inv.save()

            MovimientoInventario.objects.create(
                producto        = detalle.producto,
                tienda          = separado.tienda,
                empleado        = request.user,
                tipo            = "entrada",
                cantidad        = detalle.cantidad,
                referencia_tipo = "cancelacion_separado",
                referencia_id   = separado.id,
                observacion     = f"Cancelación separado #{separado.id}",
            )

        separado.estado = "cancelado"
        separado.save()

        return Response({
            "detail": f"Separado #{separado.id} cancelado. Stock restaurado. ✅",
            "productos_restaurados": [
                {
                    "producto": d.producto.nombre,
                    "cantidad": float(d.cantidad),
                }
                for d in separado.detalles.all()
            ]
        })
    
class AlertasSeparadosView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        hoy     = timezone.now().date()
        en3dias = hoy + timedelta(days=3)

        qs = Separado.objects.filter(
            estado='activo',
            fecha_limite__isnull=False  # ✅ única línea nueva
        ).select_related('cliente', 'tienda')

        if request.user.rol == 'cajero':
            qs = qs.filter(tienda_id=request.user.tienda_id)
        else:
            tienda_id = request.query_params.get('tienda_id')
            if tienda_id:
                qs = qs.filter(tienda_id=tienda_id)

        vencidos   = qs.filter(fecha_limite__lt=hoy)
        por_vencer = qs.filter(fecha_limite__gte=hoy, fecha_limite__lte=en3dias)

        def serializar(sep):
            return {
                'id':              sep.id,
                'cliente':         f"{sep.cliente.nombre} {sep.cliente.apellido}",
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
    

# ✅ NUEVO — para el reporte del día en Flutter
class AbonosPorFechaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        fecha     = request.query_params.get("fecha")
        tienda_id = request.query_params.get("tienda_id")

        if not fecha:
            return Response({"error": "Parámetro 'fecha' requerido."}, status=400)

        qs = AbonoSeparado.objects.select_related(
            "separado__cliente", "empleado"
        ).filter(created_at__date=fecha)

        if request.user.rol == "cajero":
            qs = qs.filter(separado__tienda_id=request.user.tienda_id)
        elif tienda_id:
            qs = qs.filter(separado__tienda_id=tienda_id)

        data = [{
            "id":              a.id,
            "separado_id":     a.separado_id,
            "cliente_nombre":  f"{a.separado.cliente.nombre} {a.separado.cliente.apellido}",
            "empleado_nombre": f"{a.empleado.nombre} {a.empleado.apellido}"
                               if a.empleado else "",
            "monto":           float(a.monto),
            "metodo_pago":     a.metodo_pago,
            "created_at":      str(a.created_at),
        } for a in qs]

        return Response({
            "abonos": data,
            "total":  sum(d["monto"] for d in data),
        })