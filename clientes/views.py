# clientes/views.py

from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.db.models import Q
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta

from core.permissions import EsAdminOSupervisor, es_superadmin, get_empresa
from productos.models import Inventario, MovimientoInventario
from .models import Cliente, Separado, AbonoSeparado
from .serializers import (
    ClienteSerializer, ClienteSimpleSerializer,
    SeparadoSerializer,
)


# ── Helper empleado ───────────────────────────────────────
def _get_empleado(request):
    if hasattr(request.user, "empleado"):
        return request.user.empleado
    return None


# ── Clientes ──────────────────────────────────────────────
class ClienteListCreateView(generics.ListCreateAPIView):
    serializer_class   = ClienteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Cliente.objects.filter(activo=True)

        if es_superadmin(self.request):
            empresa_id = self.request.query_params.get("empresa")
            if empresa_id:
                qs = qs.filter(empresa_id=empresa_id)
        else:
            qs = qs.filter(empresa=get_empresa(self.request))

        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(nombre__icontains=q)     |
                Q(apellido__icontains=q)   |
                Q(cedula_nit__icontains=q) |
                Q(telefono__icontains=q)
            )
        return qs.order_by("nombre")

    def perform_create(self, serializer):
        if es_superadmin(self.request):
            empresa_id = self.request.data.get("empresa")
            if not empresa_id:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied(
                    "El superadmin debe especificar una empresa.")
            serializer.save()
        else:
            serializer.save(empresa=get_empresa(self.request))


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
        qs = Cliente.objects.filter(activo=True)

        if es_superadmin(self.request):
            empresa_id = self.request.query_params.get("empresa")
            if empresa_id:
                qs = qs.filter(empresa_id=empresa_id)
        else:
            qs = qs.filter(empresa=get_empresa(self.request))

        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(nombre__icontains=q) | Q(cedula_nit__icontains=q))
        return qs.order_by("nombre")


# ── Separados ─────────────────────────────────────────────
class SeparadoListCreateView(generics.ListCreateAPIView):
    serializer_class   = SeparadoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Separado.objects.select_related(
            "cliente", "tienda", "empleado"
        ).prefetch_related("detalles", "abonos")

        if es_superadmin(self.request):
            empresa_id = self.request.query_params.get("empresa")
            if empresa_id:
                qs = qs.filter(tienda__empresa_id=empresa_id)
        else:
            qs = qs.filter(tienda__empresa=get_empresa(self.request))

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

    def perform_create(self, serializer):
        serializer.save(empleado=_get_empleado(self.request))


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

        monto = request.data.get("monto")
        if not monto or float(monto) <= 0:
            return Response(
                {"error": "El monto debe ser mayor a 0."}, status=400)

        monto       = Decimal(str(monto))
        metodo_pago = request.data.get("metodo_pago", "efectivo")

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

        from caja.models import SesionCaja, MovimientoCaja
        sesion = SesionCaja.objects.filter(
            tienda_id=separado.tienda_id,
            estado="abierta",
        ).first()

        if sesion:
            MovimientoCaja.objects.create(
                sesion        = sesion,
                tipo          = "abono_separado",
                metodo_pago   = metodo_pago,
                monto         = monto,
                referencia_id = separado.id,
                empleado      = _get_empleado(request),
                descripcion   = (
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
            separado = Separado.objects.prefetch_related(
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
                empleado        = _get_empleado(request),
                tipo            = "entrada",
                cantidad        = detalle.cantidad,
                referencia_tipo = "cancelacion_separado",
                referencia_id   = separado.id,
                observacion     = f"Cancelación separado #{separado.id}",
            )

        if separado.abono_acumulado > 0:
            from caja.models import SesionCaja, MovimientoCaja
            sesion = SesionCaja.objects.filter(
                tienda_id=separado.tienda_id,
                estado="abierta",
            ).first()
            if sesion:
                MovimientoCaja.objects.create(
                    sesion        = sesion,
                    tipo          = "cancelacion_separado",
                    metodo_pago   = "efectivo",
                    monto         = separado.abono_acumulado,
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
            "detail": f"Separado #{separado.id} cancelado. "
                      f"Stock restaurado. ✅",
            "productos_restaurados": [
                {
                    "producto": d.producto.nombre,
                    "cantidad": float(d.cantidad),
                }
                for d in separado.detalles.all()
            ],
        })


# ── Alertas de separados ──────────────────────────────────
class AlertasSeparadosView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        hoy     = timezone.now().date()
        en3dias = hoy + timedelta(days=3)

        qs = Separado.objects.filter(
            estado='activo',
            fecha_limite__isnull=False,
        ).select_related('cliente', 'tienda')

        if es_superadmin(request):
            empresa_id = request.query_params.get("empresa")
            if empresa_id:
                qs = qs.filter(tienda__empresa_id=empresa_id)
        else:
            qs = qs.filter(tienda__empresa=get_empresa(request))

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


# ── Abonos por fecha ──────────────────────────────────────
class AbonosPorFechaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        fecha     = request.query_params.get("fecha")
        tienda_id = request.query_params.get("tienda_id")

        if not fecha:
            return Response(
                {"error": "Parámetro 'fecha' requerido."}, status=400)

        qs = AbonoSeparado.objects.select_related(
            "separado__cliente", "empleado")

        if es_superadmin(request):
            empresa_id = request.query_params.get("empresa")
            if empresa_id:
                qs = qs.filter(
                    separado__tienda__empresa_id=empresa_id)
        else:
            qs = qs.filter(
                separado__tienda__empresa=get_empresa(request))

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