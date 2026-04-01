from decimal import Decimal
from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count
from django.db.models.functions import TruncDate

from .models import Gasto
from .serializers import GastoSerializer
from ventas.models import Venta
from caja.models import SesionCaja


# ── Clases de permisos ────────────────────────────────
class EsAdminOSupervisor(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and \
               request.user.rol in ["admin", "supervisor"]


class EsAdminSupervisorOCajero(IsAuthenticated):
    """Permite a cualquier rol autenticado."""
    def has_permission(self, request, view):
        return super().has_permission(request, view) and \
               request.user.rol in ["admin", "supervisor", "cajero"]


# ── Gastos ────────────────────────────────────────────
class GastoListCreateView(generics.ListCreateAPIView):
    serializer_class = GastoSerializer

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated()]
        return [EsAdminSupervisorOCajero()]

    def get_queryset(self):
        from django.utils import timezone

        qs   = Gasto.objects.select_related("tienda", "empleado", "sesion_caja")
        user = self.request.user

        # ✅ Fecha del query param o hoy por defecto
        fecha = self.request.query_params.get("fecha") or str(timezone.now().date())

        # Cajero: solo ve su tienda + filtro por fecha
        if user.rol == 'cajero':
            return qs.filter(
                tienda_id=user.tienda_id,
                created_at__date=fecha,     # ✅ FIX: antes ignoraba la fecha
            ).order_by("-created_at")

        # Admin/Supervisor con filtros opcionales
        tienda_id = self.request.query_params.get("tienda_id")
        categoria = self.request.query_params.get("categoria")

        qs = qs.filter(created_at__date=fecha)  # ✅ siempre filtra por fecha
        if tienda_id: qs = qs.filter(tienda_id=tienda_id)
        if categoria: qs = qs.filter(categoria=categoria)
        return qs.order_by("-created_at")

    def perform_create(self, serializer):
        tienda_id = self.request.data.get("tienda")
        sesion    = SesionCaja.objects.filter(
            tienda_id=tienda_id, estado="abierta"
        ).first()
        serializer.save(empleado=self.request.user, sesion_caja=sesion)

class GastoDetailView(generics.RetrieveDestroyAPIView):
    queryset           = Gasto.objects.all()
    serializer_class   = GastoSerializer
    permission_classes = [EsAdminOSupervisor]  # ✅ eliminar solo admin/supervisor


# ── Resumen diario (admin + supervisor + cajero) ──────
class ResumenDiarioView(APIView):
    permission_classes = [EsAdminSupervisorOCajero]

    def get(self, request):
        from django.utils import timezone
        fecha     = request.query_params.get("fecha") or timezone.now().date()
        tienda_id = request.query_params.get("tienda_id")

        # Cajero solo ve su propia tienda
        if request.user.rol == "cajero":
            tienda_id = str(request.user.tienda_id)

        ventas_qs = Venta.objects.filter(
            estado="completada", created_at__date=fecha)
        gastos_qs = Gasto.objects.filter(created_at__date=fecha)

        if tienda_id:
            ventas_qs = ventas_qs.filter(tienda_id=tienda_id)
            gastos_qs = gastos_qs.filter(tienda_id=tienda_id)

        total_ventas = ventas_qs.aggregate(t=Sum("total"))["t"] or Decimal("0")
        total_gastos = gastos_qs.aggregate(t=Sum("monto"))["t"] or Decimal("0")
        por_metodo   = ventas_qs.values("metodo_pago").annotate(
            total=Sum("total"), cantidad=Count("id"))

        return Response({
            "fecha":          str(fecha),
            "total_ventas":   float(total_ventas),
            "num_ventas":     ventas_qs.count(),
            "total_gastos":   float(total_gastos),
            "utilidad_bruta": float(total_ventas - total_gastos),
            "ventas_por_metodo_pago": [
                {
                    "metodo":   v["metodo_pago"],
                    "total":    float(v["total"]),
                    "cantidad": v["cantidad"],
                }
                for v in por_metodo
            ],
        })


# ── Resumen mensual (solo admin + supervisor) ─────────
class ResumenMensualView(APIView):
    permission_classes = [EsAdminOSupervisor]

    def get(self, request):
        anio      = request.query_params.get("anio", "2026")
        mes       = request.query_params.get("mes",  "3")
        tienda_id = request.query_params.get("tienda_id")

        ventas_qs = Venta.objects.filter(
            estado="completada",
            created_at__year=anio,
            created_at__month=mes,
        )
        gastos_qs = Gasto.objects.filter(
            created_at__year=anio,
            created_at__month=mes,
        )
        if tienda_id:
            ventas_qs = ventas_qs.filter(tienda_id=tienda_id)
            gastos_qs = gastos_qs.filter(tienda_id=tienda_id)

        total_mes  = ventas_qs.aggregate(t=Sum("total"))["t"] or Decimal("0")
        gastos_mes = gastos_qs.aggregate(t=Sum("monto"))["t"] or Decimal("0")
        por_dia    = (
            ventas_qs
            .annotate(dia=TruncDate("created_at"))
            .values("dia")
            .annotate(total=Sum("total"), cantidad=Count("id"))
            .order_by("dia")
        )

        return Response({
            "anio":           int(anio),
            "mes":            int(mes),
            "total_ventas":   float(total_mes),
            "total_gastos":   float(gastos_mes),
            "utilidad_bruta": float(total_mes - gastos_mes),
            "ventas_por_dia": [
                {
                    "dia":      str(v["dia"]),
                    "total":    float(v["total"]),
                    "cantidad": v["cantidad"],
                }
                for v in por_dia
            ],
        })


# ── Top productos (admin + supervisor + cajero) ───────
class ProductosMasVendidosView(APIView):
    permission_classes = [EsAdminSupervisorOCajero]

    def get(self, request):
        from ventas.models import DetalleVenta
        tienda_id = request.query_params.get("tienda_id")
        fecha_ini = request.query_params.get("fecha_ini")
        fecha_fin = request.query_params.get("fecha_fin")

        # Cajero solo ve su propia tienda
        if request.user.rol == "cajero":
            tienda_id = str(request.user.tienda_id)

        qs = DetalleVenta.objects.filter(venta__estado="completada")
        if tienda_id: qs = qs.filter(venta__tienda_id=tienda_id)
        if fecha_ini: qs = qs.filter(venta__created_at__date__gte=fecha_ini)
        if fecha_fin: qs = qs.filter(venta__created_at__date__lte=fecha_fin)

        top = qs.values("producto__nombre").annotate(
            total_cantidad=Sum("cantidad"),
            total_ingresos=Sum("subtotal"),
        ).order_by("-total_cantidad")[:10]

        return Response([
            {
                "producto":       t["producto__nombre"],
                "total_vendido":  float(t["total_cantidad"]),
                "total_ingresos": float(t["total_ingresos"]),
            }
            for t in top
        ])