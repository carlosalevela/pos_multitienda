# contabilidad/views.py

from decimal import Decimal
from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone

from core.permissions import EsAdminOSupervisor, es_superadmin, get_empresa
from .models import Gasto
from .serializers import GastoSerializer
from ventas.models import Venta
from caja.models import SesionCaja
from devoluciones.models import Devolucion


CATEGORIAS_SOLO_ADMIN = {
    'arriendo', 'nomina', 'servicios', 'mercancia',
    'recibo', 'proveedor', 'impuesto', 'administrativo',
}


# ── Permiso local ─────────────────────────────────────────
# EsAdminOSupervisor viene de core.permissions
# Este permiso incluye cajero y no existe en core
class EsAdminSupervisorOCajero(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and \
               request.user.rol in [
                   "superadmin", "admin", "supervisor", "cajero"]


# ── Helper devoluciones ───────────────────────────────────
def _devoluciones_qs_base(empresa=None):
    """QuerySet base de devoluciones procesadas, opcionalmente scoped."""
    qs = Devolucion.objects.filter(estado="procesada")
    if empresa:
        qs = qs.filter(tienda__empresa=empresa)
    return qs


# ── Gastos ────────────────────────────────────────────────
class GastoListCreateView(generics.ListCreateAPIView):
    serializer_class = GastoSerializer

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated()]
        return [EsAdminSupervisorOCajero()]

    def get_queryset(self):
        qs = Gasto.objects.select_related(
            "tienda", "empleado", "sesion_caja")

        if es_superadmin(self.request):
            empresa_id = self.request.query_params.get("empresa")
            if empresa_id:
                qs = qs.filter(tienda__empresa_id=empresa_id)
        else:
            qs = qs.filter(tienda__empresa=get_empresa(self.request))

        user = self.request.user
        if user.rol == 'cajero':
            fecha = (self.request.query_params.get("fecha") or
                     str(timezone.now().date()))
            return qs.filter(
                tienda_id=user.tienda_id,
                created_at__date=fecha,
                visibilidad='todos',
            ).order_by("-created_at")

        fecha_ini   = self.request.query_params.get("fecha_ini")
        fecha_fin   = self.request.query_params.get("fecha_fin")
        fecha       = self.request.query_params.get("fecha")
        tienda_id   = self.request.query_params.get("tienda_id")
        categoria   = self.request.query_params.get("categoria")
        visibilidad = self.request.query_params.get("visibilidad")

        if fecha_ini and fecha_fin:
            qs = qs.filter(
                created_at__date__gte=fecha_ini,
                created_at__date__lte=fecha_fin,
            )
        elif fecha:
            qs = qs.filter(created_at__date=fecha)
        else:
            qs = qs.filter(created_at__date=timezone.now().date())

        if tienda_id:   qs = qs.filter(tienda_id=tienda_id)
        if categoria:   qs = qs.filter(categoria__iexact=categoria)
        if visibilidad: qs = qs.filter(visibilidad=visibilidad)

        return qs.order_by("-created_at")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def perform_create(self, serializer):
        tienda_id = self.request.data.get("tienda")

        if es_superadmin(self.request):
            empresa = None   # superadmin no tiene empresa propia
        else:
            empresa = get_empresa(self.request)

        sesion_filtro = {"tienda_id": tienda_id, "estado": "abierta"}
        if empresa:
            sesion_filtro["tienda__empresa"] = empresa

        sesion = SesionCaja.objects.filter(**sesion_filtro).first()

        categoria           = self.request.data.get(
            "categoria", "").lower().strip()
        visibilidad_enviada = self.request.data.get("visibilidad", "")
        rol                 = self.request.user.rol

        if visibilidad_enviada in ('todos', 'solo_admin'):
            visibilidad = visibilidad_enviada
        elif rol == 'cajero':
            visibilidad = 'todos'
        elif categoria in CATEGORIAS_SOLO_ADMIN:
            visibilidad = 'solo_admin'
        else:
            visibilidad = 'todos'

        serializer.save(
            empleado    = self.request.user,
            sesion_caja = sesion,
            visibilidad = visibilidad,
        )


class GastoDetailView(generics.RetrieveDestroyAPIView):
    serializer_class   = GastoSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        if es_superadmin(self.request):
            return Gasto.objects.all()
        return Gasto.objects.filter(
            tienda__empresa=get_empresa(self.request))


# ── Resumen diario ────────────────────────────────────────
class ResumenDiarioView(APIView):
    permission_classes = [EsAdminSupervisorOCajero]

    def get(self, request):
        fecha     = request.query_params.get("fecha") or timezone.now().date()
        tienda_id = request.query_params.get("tienda_id")

        if request.user.rol == "cajero":
            tienda_id = str(request.user.tienda_id)

        # base querysets
        ventas_qs = Venta.objects.filter(
            estado="completada", created_at__date=fecha)
        gastos_qs = Gasto.objects.filter(created_at__date=fecha)
        dev_qs    = Devolucion.objects.filter(
            estado="procesada", created_at__date=fecha)

        if es_superadmin(request):
            empresa_id = request.query_params.get("empresa")
            if empresa_id:
                ventas_qs = ventas_qs.filter(
                    tienda__empresa_id=empresa_id)
                gastos_qs = gastos_qs.filter(
                    tienda__empresa_id=empresa_id)
                dev_qs    = dev_qs.filter(
                    tienda__empresa_id=empresa_id)
        else:
            empresa   = get_empresa(request)
            ventas_qs = ventas_qs.filter(tienda__empresa=empresa)
            gastos_qs = gastos_qs.filter(tienda__empresa=empresa)
            dev_qs    = dev_qs.filter(tienda__empresa=empresa)

        if request.user.rol == "cajero":
            gastos_qs = gastos_qs.filter(visibilidad='todos')
            dev_qs    = dev_qs.filter(
                tienda_id=request.user.tienda_id)

        if tienda_id:
            ventas_qs = ventas_qs.filter(tienda_id=tienda_id)
            gastos_qs = gastos_qs.filter(tienda_id=tienda_id)
            dev_qs    = dev_qs.filter(tienda_id=tienda_id)

        total_ventas      = ventas_qs.aggregate(
            t=Sum("total"))["t"] or Decimal("0")
        total_gastos      = gastos_qs.aggregate(
            t=Sum("monto"))["t"] or Decimal("0")
        total_devoluciones = dev_qs.aggregate(
            t=Sum("total_devuelto"))["t"] or Decimal("0")

        por_metodo     = ventas_qs.values("metodo_pago").annotate(
            total=Sum("total"), cantidad=Count("id"))
        dev_por_metodo = dev_qs.values("metodo_devolucion").annotate(
            total=Sum("total_devuelto"), cantidad=Count("id"))

        gastos_por_categoria = []
        if request.user.rol not in ("cajero",):
            gastos_por_categoria = [
                {
                    "categoria": g["categoria"],
                    "total":     float(g["total"]),
                    "cantidad":  g["cantidad"],
                }
                for g in (
                    gastos_qs
                    .values("categoria")
                    .annotate(total=Sum("monto"), cantidad=Count("id"))
                    .order_by("-total")
                )
            ]

        return Response({
            "fecha":              str(fecha),
            "total_ventas":       float(total_ventas),
            "num_ventas":         ventas_qs.count(),
            "total_gastos":       float(total_gastos),
            "total_devoluciones": float(total_devoluciones),
            "num_devoluciones":   dev_qs.count(),
            "total_neto":         float(total_ventas - total_devoluciones),
            "utilidad_bruta":     float(
                total_ventas - total_devoluciones - total_gastos),
            "ventas_por_metodo_pago": [
                {
                    "metodo":   v["metodo_pago"],
                    "total":    float(v["total"]),
                    "cantidad": v["cantidad"],
                }
                for v in por_metodo
            ],
            "devoluciones_por_metodo": [
                {
                    "metodo":   d["metodo_devolucion"],
                    "total":    float(d["total"]),
                    "cantidad": d["cantidad"],
                }
                for d in dev_por_metodo
            ],
            "gastos_por_categoria": gastos_por_categoria,
        })


# ── Resumen mensual ───────────────────────────────────────
class ResumenMensualView(APIView):
    permission_classes = [EsAdminOSupervisor]

    def get(self, request):
        anio      = request.query_params.get(
            "anio", str(timezone.now().year))
        mes       = request.query_params.get(
            "mes", str(timezone.now().month))
        tienda_id = request.query_params.get("tienda_id")

        ventas_qs = Venta.objects.filter(
            estado="completada",
            created_at__year=anio,
            created_at__month=mes,
        )
        gastos_qs = Gasto.objects.filter(
            created_at__year=anio, created_at__month=mes)
        dev_qs    = Devolucion.objects.filter(
            estado="procesada",
            created_at__year=anio,
            created_at__month=mes,
        )

        if es_superadmin(request):
            empresa_id = request.query_params.get("empresa")
            if empresa_id:
                ventas_qs = ventas_qs.filter(
                    tienda__empresa_id=empresa_id)
                gastos_qs = gastos_qs.filter(
                    tienda__empresa_id=empresa_id)
                dev_qs    = dev_qs.filter(
                    tienda__empresa_id=empresa_id)
        else:
            empresa   = get_empresa(request)
            ventas_qs = ventas_qs.filter(tienda__empresa=empresa)
            gastos_qs = gastos_qs.filter(tienda__empresa=empresa)
            dev_qs    = dev_qs.filter(tienda__empresa=empresa)

        if tienda_id:
            ventas_qs = ventas_qs.filter(tienda_id=tienda_id)
            gastos_qs = gastos_qs.filter(tienda_id=tienda_id)
            dev_qs    = dev_qs.filter(tienda_id=tienda_id)

        total_mes        = ventas_qs.aggregate(
            t=Sum("total"))["t"] or Decimal("0")
        gastos_mes       = gastos_qs.aggregate(
            t=Sum("monto"))["t"] or Decimal("0")
        devoluciones_mes = dev_qs.aggregate(
            t=Sum("total_devuelto"))["t"] or Decimal("0")

        por_dia = (
            ventas_qs.annotate(dia=TruncDate("created_at"))
            .values("dia")
            .annotate(total=Sum("total"), cantidad=Count("id"))
            .order_by("dia")
        )
        gastos_por_categoria = (
            gastos_qs.values("categoria")
            .annotate(total=Sum("monto"))
            .order_by("-total")
        )
        gastos_por_dia = (
            gastos_qs.annotate(dia=TruncDate("created_at"))
            .values("dia")
            .annotate(total=Sum("monto"))
            .order_by("dia")
        )
        devoluciones_por_dia = (
            dev_qs.annotate(dia=TruncDate("created_at"))
            .values("dia")
            .annotate(total=Sum("total_devuelto"), cantidad=Count("id"))
            .order_by("dia")
        )

        return Response({
            "anio":               int(anio),
            "mes":                int(mes),
            "total_ventas":       float(total_mes),
            "total_gastos":       float(gastos_mes),
            "total_devoluciones": float(devoluciones_mes),
            "total_neto":         float(total_mes - devoluciones_mes),
            "utilidad_bruta":     float(
                total_mes - devoluciones_mes - gastos_mes),
            "ventas_por_dia": [
                {
                    "dia":      str(v["dia"]),
                    "total":    float(v["total"]),
                    "cantidad": v["cantidad"],
                }
                for v in por_dia
            ],
            "gastos_por_categoria": [
                {"categoria": g["categoria"], "total": float(g["total"])}
                for g in gastos_por_categoria
            ],
            "gastos_por_dia": [
                {"dia": str(g["dia"]), "total": float(g["total"])}
                for g in gastos_por_dia
            ],
            "devoluciones_por_dia": [
                {
                    "dia":      str(d["dia"]),
                    "total":    float(d["total"]),
                    "cantidad": d["cantidad"],
                }
                for d in devoluciones_por_dia
            ],
        })


# ── Top productos ─────────────────────────────────────────
class ProductosMasVendidosView(APIView):
    permission_classes = [EsAdminSupervisorOCajero]

    def get(self, request):
        from ventas.models import DetalleVenta

        tienda_id = request.query_params.get("tienda_id")
        fecha_ini = request.query_params.get("fecha_ini")
        fecha_fin = request.query_params.get("fecha_fin")

        if request.user.rol == "cajero":
            tienda_id = str(request.user.tienda_id)

        qs = DetalleVenta.objects.filter(venta__estado="completada")

        if es_superadmin(request):
            empresa_id = request.query_params.get("empresa")
            if empresa_id:
                qs = qs.filter(venta__tienda__empresa_id=empresa_id)
        else:
            qs = qs.filter(
                venta__tienda__empresa=get_empresa(request))

        if tienda_id: qs = qs.filter(venta__tienda_id=tienda_id)
        if fecha_ini: qs = qs.filter(
            venta__created_at__date__gte=fecha_ini)
        if fecha_fin: qs = qs.filter(
            venta__created_at__date__lte=fecha_fin)

        top = (
            qs.values("producto__nombre")
            .annotate(
                total_cantidad=Sum("cantidad"),
                total_ingresos=Sum("subtotal"),
            )
            .order_by("-total_cantidad")[:10]
        )

        return Response([
            {
                "producto":       t["producto__nombre"],
                "total_vendido":  float(t["total_cantidad"]),
                "total_ingresos": float(t["total_ingresos"]),
            }
            for t in top
        ])


# ── Resumen anual ─────────────────────────────────────────
class ResumenAnualView(APIView):
    permission_classes = [EsAdminOSupervisor]

    def get(self, request):
        anio      = int(request.query_params.get(
            "anio", timezone.now().year))
        tienda_id = request.query_params.get("tienda_id")

        ventas_qs = Venta.objects.filter(
            estado="completada", created_at__year=anio)
        gastos_qs = Gasto.objects.filter(created_at__year=anio)
        dev_qs    = Devolucion.objects.filter(
            estado="procesada", created_at__year=anio)

        if es_superadmin(request):
            empresa_id = request.query_params.get("empresa")
            if empresa_id:
                ventas_qs = ventas_qs.filter(
                    tienda__empresa_id=empresa_id)
                gastos_qs = gastos_qs.filter(
                    tienda__empresa_id=empresa_id)
                dev_qs    = dev_qs.filter(
                    tienda__empresa_id=empresa_id)
        else:
            empresa   = get_empresa(request)
            ventas_qs = ventas_qs.filter(tienda__empresa=empresa)
            gastos_qs = gastos_qs.filter(tienda__empresa=empresa)
            dev_qs    = dev_qs.filter(tienda__empresa=empresa)

        if tienda_id:
            ventas_qs = ventas_qs.filter(tienda_id=tienda_id)
            gastos_qs = gastos_qs.filter(tienda_id=tienda_id)
            dev_qs    = dev_qs.filter(tienda_id=tienda_id)

        total_anio        = ventas_qs.aggregate(
            t=Sum("total"))["t"] or Decimal("0")
        gastos_anio       = gastos_qs.aggregate(
            t=Sum("monto"))["t"] or Decimal("0")
        devoluciones_anio = dev_qs.aggregate(
            t=Sum("total_devuelto"))["t"] or Decimal("0")

        por_mes_ventas = {
            v["mes"].month: v
            for v in ventas_qs
                .annotate(mes=TruncMonth("created_at"))
                .values("mes")
                .annotate(total=Sum("total"), cantidad=Count("id"))
        }
        por_mes_gastos = {
            g["mes"].month: float(g["total"])
            for g in gastos_qs
                .annotate(mes=TruncMonth("created_at"))
                .values("mes")
                .annotate(total=Sum("monto"))
        }
        por_mes_devoluciones = {
            d["mes"].month: float(d["total"])
            for d in dev_qs
                .annotate(mes=TruncMonth("created_at"))
                .values("mes")
                .annotate(total=Sum("total_devuelto"))
        }

        MESES = [
            "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre",
            "Diciembre",
        ]

        meses = []
        for m in range(1, 13):
            ventas_m = float(
                por_mes_ventas.get(m, {}).get("total", 0) or 0)
            gastos_m = por_mes_gastos.get(m, 0)
            dev_m    = por_mes_devoluciones.get(m, 0)
            meses.append({
                "mes":          m,
                "nombre":       MESES[m],
                "ventas":       ventas_m,
                "devoluciones": dev_m,
                "neto":         ventas_m - dev_m,
                "gastos":       gastos_m,
                "utilidad":     ventas_m - dev_m - gastos_m,
                "cantidad":     por_mes_ventas.get(m, {}).get(
                    "cantidad", 0) or 0,
            })

        return Response({
            "anio":               anio,
            "total_ventas":       float(total_anio),
            "total_gastos":       float(gastos_anio),
            "total_devoluciones": float(devoluciones_anio),
            "total_neto":         float(total_anio - devoluciones_anio),
            "utilidad_bruta":     float(
                total_anio - devoluciones_anio - gastos_anio),
            "meses": meses,
        })


# ── Gastos por rango ──────────────────────────────────────
class GastosResumenRangoView(APIView):
    permission_classes = [EsAdminOSupervisor]

    def get(self, request):
        fecha_ini = request.query_params.get("fecha_ini")
        fecha_fin = request.query_params.get("fecha_fin")
        tienda_id = request.query_params.get("tienda_id")
        categoria = request.query_params.get("categoria")

        if not fecha_ini or not fecha_fin:
            return Response(
                {"error": "fecha_ini y fecha_fin son requeridos"},
                status=400)

        qs = Gasto.objects.filter(
            created_at__date__gte=fecha_ini,
            created_at__date__lte=fecha_fin,
        )

        if es_superadmin(request):
            empresa_id = request.query_params.get("empresa")
            if empresa_id:
                qs = qs.filter(tienda__empresa_id=empresa_id)
        else:
            qs = qs.filter(tienda__empresa=get_empresa(request))

        if tienda_id: qs = qs.filter(tienda_id=tienda_id)
        if categoria: qs = qs.filter(categoria__iexact=categoria)

        total = qs.aggregate(t=Sum("monto"))["t"] or Decimal("0")

        por_categoria = (
            qs.values("categoria")
            .annotate(total=Sum("monto"), cantidad=Count("id"))
            .order_by("-total")
        )
        por_dia = (
            qs.annotate(dia=TruncDate("created_at"))
            .values("dia")
            .annotate(total=Sum("monto"), cantidad=Count("id"))
            .order_by("dia")
        )

        return Response({
            "fecha_ini": fecha_ini,
            "fecha_fin": fecha_fin,
            "total":     float(total),
            "cantidad":  qs.count(),
            "por_categoria": [
                {
                    "categoria": g["categoria"],
                    "total":     float(g["total"]),
                    "cantidad":  g["cantidad"],
                }
                for g in por_categoria
            ],
            "por_dia": [
                {
                    "dia":      str(g["dia"]),
                    "total":    float(g["total"]),
                    "cantidad": g["cantidad"],
                }
                for g in por_dia
            ],
        })