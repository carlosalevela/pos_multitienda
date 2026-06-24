from datetime import timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from contabilidad.models import Gasto
from core.permissions import EsAdminOSupervisor, es_superadmin, get_empresa
from devoluciones.models import Devolucion
from ventas.models import Venta

from .models import SesionCaja
from .serializers import (
    AbrirCajaSerializer, CerrarCajaSerializer,
    SesionCajaResumenSerializer, SesionCajaSerializer,
)


# ── Abrir caja ────────────────────────────────────────────────
class AbrirCajaView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AbrirCajaSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        tienda_id = request.user.tienda_id
        if not tienda_id:
            return Response(
                {"error": "Este usuario no tiene una tienda asignada."}, status=400
            )

        if not es_superadmin(request):
            empresa = get_empresa(request)
            if request.user.tienda.empresa != empresa:
                return Response(
                    {"error": "La tienda asignada no pertenece a tu empresa."}, status=403
                )

        monto_inicial  = serializer.validated_data["monto_inicial"]
        sesion_abierta = SesionCaja.objects.filter(
            tienda_id=tienda_id, estado="abierta"
        ).first()

        if sesion_abierta:
            return Response({
                "error":      "Ya existe una caja abierta en esta tienda.",
                "sesion_id":  sesion_abierta.id,
                "abierta_por": (
                    f"{sesion_abierta.empleado.nombre} {sesion_abierta.empleado.apellido}"
                    if sesion_abierta.empleado else "Desconocido"
                ),
                "desde": sesion_abierta.fecha_apertura,
            }, status=400)

        sesion = SesionCaja.objects.create(
            tienda_id=tienda_id,
            empleado=request.user,
            monto_inicial=monto_inicial,
            estado="abierta",
        )

        return Response({
            "detail":         "Caja abierta correctamente.",
            "sesion_id":      sesion.id,
            "tienda_id":      tienda_id,
            "monto_inicial":  float(monto_inicial),
            "fecha_apertura": sesion.fecha_apertura,
        }, status=201)


# ── Cerrar caja ───────────────────────────────────────────────
class CerrarCajaView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            filtro = {} if es_superadmin(request) else {"tienda__empresa": get_empresa(request)}
            sesion = SesionCaja.objects.get(pk=pk, **filtro)
        except SesionCaja.DoesNotExist:
            return Response({"error": "Sesión de caja no encontrada."}, status=404)

        if sesion.estado == "cerrada":
            return Response({"error": "Esta caja ya está cerrada."}, status=400)

        serializer = CerrarCajaSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        monto_real    = serializer.validated_data["monto_final_real"]
        observaciones = serializer.validated_data.get("observaciones", "")

        total_ventas = Venta.objects.filter(
            sesion_caja=sesion, estado="completada",
            metodo_pago__in=["efectivo", "mixto"],
        ).aggregate(t=Sum("total"))["t"] or Decimal("0")

        total_gastos = Gasto.objects.filter(
            sesion_caja=sesion, metodo_pago="efectivo",
        ).aggregate(t=Sum("monto"))["t"] or Decimal("0")

        base_a = sesion.movimientos.filter(tipo="abono_separado")
        abonos_efectivo      = base_a.filter(metodo_pago="efectivo").aggregate(t=Sum("monto"))["t"] or Decimal("0")
        abonos_tarjeta       = base_a.filter(metodo_pago="tarjeta").aggregate(t=Sum("monto"))["t"] or Decimal("0")
        abonos_transferencia = base_a.filter(metodo_pago="transferencia").aggregate(t=Sum("monto"))["t"] or Decimal("0")
        abonos_total         = abonos_efectivo + abonos_tarjeta + abonos_transferencia

        base_d = Devolucion.objects.filter(venta__sesion_caja=sesion, estado="procesada")
        dev_efectivo     = base_d.filter(tipo="devolucion", metodo_devolucion="efectivo").aggregate(t=Sum("total_devuelto"))["t"] or Decimal("0")
        cambios_cobrar   = base_d.filter(tipo="cambio", tipo_diferencia="cobrar",   metodo_pago_diferencia="efectivo").aggregate(t=Sum("diferencia"))["t"] or Decimal("0")
        cambios_devolver = base_d.filter(tipo="cambio", tipo_diferencia="devolver", metodo_pago_diferencia="efectivo").aggregate(t=Sum("diferencia"))["t"] or Decimal("0")
        neto_dev_efectivo = dev_efectivo + cambios_devolver - cambios_cobrar

        monto_sistema = (
            sesion.monto_inicial + total_ventas + abonos_efectivo - total_gastos - neto_dev_efectivo
        )
        diferencia = monto_real - monto_sistema

        sesion.monto_final_sistema = monto_sistema
        sesion.monto_final_real    = monto_real
        sesion.diferencia          = diferencia
        sesion.observaciones       = observaciones
        sesion.estado              = "cerrada"
        sesion.fecha_cierre        = timezone.now()
        sesion.save()

        return Response({
            "detail":               "Caja cerrada correctamente.",
            "sesion_id":            sesion.id,
            "monto_inicial":        float(sesion.monto_inicial),
            "total_ventas":         float(total_ventas),
            "total_gastos":         float(total_gastos),
            "abonos_efectivo":      float(abonos_efectivo),
            "abonos_tarjeta":       float(abonos_tarjeta),
            "abonos_transferencia": float(abonos_transferencia),
            "abonos_total":         float(abonos_total),
            "total_devoluciones":   float(neto_dev_efectivo),
            "monto_final_sistema":  float(monto_sistema),
            "monto_final_real":     float(monto_real),
            "diferencia":           float(diferencia),
            "estado_diferencia": (
                "Cuadre exacto" if diferencia == 0
                else f"Faltante ${abs(diferencia)}" if diferencia < 0
                else f"Sobrante ${diferencia}"
            ),
        })


# ── Sesión activa de una tienda ───────────────────────────────
class SesionActivaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, tienda_id):
        filtro = {"tienda_id": tienda_id, "estado": "abierta"}
        if not es_superadmin(request):
            filtro["tienda__empresa"] = get_empresa(request)

        sesion = (
            SesionCaja.objects
            .filter(**filtro)
            .select_related("empleado", "tienda")
            .first()
        )

        if not sesion:
            return Response({"error": "No hay caja abierta en esta tienda."}, status=404)

        return Response(SesionCajaSerializer(sesion, context={"request": request}).data)


# ── Historial (lista ligera sin N+1) ─────────────────────────
class SesionCajaListView(generics.ListAPIView):
    serializer_class   = SesionCajaResumenSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = (
            SesionCaja.objects
            .select_related("empleado", "tienda")
            .annotate(**SesionCajaResumenSerializer.anotaciones())
            .order_by("-fecha_apertura")
        )

        if es_superadmin(self.request):
            empresa_id = self.request.query_params.get("empresa")
            if empresa_id:
                qs = qs.filter(tienda__empresa_id=empresa_id)
        else:
            qs = qs.filter(tienda__empresa=get_empresa(self.request))

        tienda_id    = self.request.query_params.get("tienda_id")
        fecha        = self.request.query_params.get("fecha")
        estado       = self.request.query_params.get("estado", "cerrada")
        mis_sesiones = self.request.query_params.get("mis_sesiones")

        if tienda_id:    qs = qs.filter(tienda_id=tienda_id)
        if fecha:        qs = qs.filter(fecha_apertura__date=fecha)
        if mis_sesiones: qs = qs.filter(empleado=self.request.user)
        return qs.filter(estado=estado)


# ── Detalle completo de sesión ────────────────────────────────
class SesionCajaDetailView(generics.RetrieveAPIView):
    serializer_class   = SesionCajaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if es_superadmin(self.request):
            return SesionCaja.objects.select_related("empleado", "tienda")
        return SesionCaja.objects.filter(
            tienda__empresa=get_empresa(self.request)
        ).select_related("empleado", "tienda")


# ── Resumen pre-cierre ────────────────────────────────────────
class ResumenCierreView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        filtro = {"pk": pk, "estado": "abierta"}
        if not es_superadmin(request):
            filtro["tienda__empresa"] = get_empresa(request)

        try:
            sesion = SesionCaja.objects.select_related("tienda", "empleado").get(**filtro)
        except SesionCaja.DoesNotExist:
            return Response({"error": "Sesión no encontrada o ya cerrada."}, status=404)

        def agg(qs):   return qs.aggregate(t=Sum("monto"))["t"]          or Decimal("0")
        def vsum(qs):  return qs.aggregate(t=Sum("total"))["t"]          or Decimal("0")
        def dsum(qs):  return qs.aggregate(t=Sum("total_devuelto"))["t"] or Decimal("0")
        def ddsum(qs): return qs.aggregate(t=Sum("diferencia"))["t"]     or Decimal("0")

        base_v = Venta.objects.filter(sesion_caja=sesion, estado="completada")
        base_g = Gasto.objects.filter(sesion_caja=sesion)
        base_d = Devolucion.objects.filter(venta__sesion_caja=sesion, estado="procesada")

        v_efectivo      = vsum(base_v.filter(metodo_pago="efectivo"))
        v_tarjeta       = vsum(base_v.filter(metodo_pago="tarjeta"))
        v_transferencia = vsum(base_v.filter(metodo_pago="transferencia"))
        v_mixto         = vsum(base_v.filter(metodo_pago="mixto"))
        total_ventas    = v_efectivo + v_tarjeta + v_transferencia + v_mixto

        g_efectivo     = agg(base_g.filter(metodo_pago="efectivo"))
        g_otros        = agg(base_g.exclude(metodo_pago="efectivo"))
        detalle_gastos = list(base_g.values("categoria", "monto", "metodo_pago"))

        base_a          = sesion.movimientos.filter(tipo="abono_separado")
        a_efectivo      = agg(base_a.filter(metodo_pago="efectivo"))
        a_transferencia = agg(base_a.filter(metodo_pago="transferencia"))
        a_tarjeta       = agg(base_a.filter(metodo_pago="tarjeta"))
        num_abonos      = base_a.count()

        dev_efectivo     = dsum(base_d.filter(tipo="devolucion", metodo_devolucion="efectivo"))
        cambios_cobrar   = ddsum(base_d.filter(tipo="cambio", tipo_diferencia="cobrar",   metodo_pago_diferencia="efectivo"))
        cambios_devolver = ddsum(base_d.filter(tipo="cambio", tipo_diferencia="devolver", metodo_pago_diferencia="efectivo"))
        neto_dev_efectivo = dev_efectivo + cambios_devolver - cambios_cobrar

        monto_esperado = (
            sesion.monto_inicial + v_efectivo + v_mixto + a_efectivo - g_efectivo - neto_dev_efectivo
        )

        nombre = (
            f"{sesion.empleado.nombre} {sesion.empleado.apellido}" if sesion.empleado else ""
        )

        return Response({
            "sesion_id":       sesion.id,
            "tienda_nombre":   sesion.tienda.nombre,
            "empleado_nombre": nombre,
            "fecha_apertura":  sesion.fecha_apertura,
            "monto_inicial":   float(sesion.monto_inicial),
            "ventas": {
                "efectivo":          float(v_efectivo),
                "tarjeta":           float(v_tarjeta),
                "transferencia":     float(v_transferencia),
                "mixto":             float(v_mixto),
                "total":             float(total_ventas),
                "num_transacciones": base_v.count(),
            },
            "gastos": {
                "efectivo": float(g_efectivo),
                "otros":    float(g_otros),
                "total":    float(g_efectivo + g_otros),
                "detalle":  detalle_gastos,
            },
            "abonos": {
                "efectivo":      float(a_efectivo),
                "transferencia": float(a_transferencia),
                "tarjeta":       float(a_tarjeta),
                "total":         float(a_efectivo + a_transferencia + a_tarjeta),
                "cantidad":      num_abonos,
            },
            "devoluciones": {
                "efectivo":         float(dev_efectivo),
                "cambios_cobrar":   float(cambios_cobrar),
                "cambios_devolver": float(cambios_devolver),
                "neto_efectivo":    float(neto_dev_efectivo),
                "cantidad":         base_d.count(),
                "cambios_producto": base_d.filter(
                    tipo="cambio", producto_reemplazo__isnull=False
                ).count(),
            },
            "monto_esperado_caja": float(monto_esperado),
        })


# ── Gastos de una sesión (cajero y superiores) ───────────────
class SesionGastosView(APIView):
    """
    GET /api/caja/{pk}/gastos/
    Devuelve los gastos registrados en una sesión de caja.
    Accesible para el cajero dueño del turno, supervisor y admin.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        filtro = {"pk": pk}
        if not es_superadmin(request):
            filtro["tienda__empresa"] = get_empresa(request)

        try:
            sesion = SesionCaja.objects.select_related("tienda", "empleado").get(**filtro)
        except SesionCaja.DoesNotExist:
            return Response({"error": "Sesión no encontrada."}, status=404)

        # Cajero solo puede ver su propio turno
        if request.user.rol == "cajero" and sesion.empleado_id != request.user.id:
            return Response({"error": "No tienes permiso para ver esta sesión."}, status=403)

        qs = Gasto.objects.filter(sesion_caja=sesion).order_by("-created_at")

        # Cajero solo ve gastos con visibilidad='todos'
        if request.user.rol == "cajero":
            qs = qs.filter(visibilidad="todos")

        gastos = list(qs.values(
            "id", "categoria", "descripcion",
            "monto", "metodo_pago", "visibilidad", "tipo_gasto", "created_at",
        ))

        totales = qs.aggregate(
            total=Sum("monto"),
            efectivo=Sum("monto", filter=Q(metodo_pago="efectivo")),
            otros=Sum("monto", filter=~Q(metodo_pago="efectivo")),
        )

        return Response({
            "sesion_id": sesion.id,
            "gastos":    gastos,
            "resumen": {
                "total":    float(totales["total"]    or 0),
                "efectivo": float(totales["efectivo"] or 0),
                "otros":    float(totales["otros"]    or 0),
                "cantidad": len(gastos),
            },
        })


# ── Dashboard de Caja (Admin / Superadmin) ────────────────────
class DashboardCajaView(APIView):
    permission_classes = [EsAdminOSupervisor]

    def get(self, request):
        hoy          = timezone.now().date()
        inicio_mes   = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        dia_semana   = timezone.now().weekday()
        inicio_semana = (timezone.now() - timedelta(days=dia_semana)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        periodo       = request.query_params.get("periodo", "mensual")
        inicio_actual = inicio_semana if periodo == "semanal" else inicio_mes
        if periodo == "semanal":
            inicio_ant = inicio_actual - timedelta(days=7)
        elif inicio_actual.month > 1:
            inicio_ant = inicio_actual.replace(month=inicio_actual.month - 1)
        else:
            inicio_ant = inicio_actual.replace(year=inicio_actual.year - 1, month=12)

        tienda_id  = request.query_params.get("tienda_id")
        superadmin = es_superadmin(request)
        empresa    = None if superadmin else get_empresa(request)
        emp_param  = request.query_params.get("empresa") if superadmin else None

        def _scope(qs, campo="empresa"):
            """Aplica filtro de empresa/tienda según rol."""
            if not superadmin:
                return qs.filter(**{campo: empresa})
            if emp_param:
                return qs.filter(**{f"{campo}_id": emp_param})
            return qs

        def _tienda(qs):
            return qs.filter(tienda_id=tienda_id) if tienda_id else qs

        # ── KPIs ──────────────────────────────────────────────
        venta_qs = _tienda(_scope(
            Venta.objects.filter(estado="completada", created_at__gte=inicio_actual)
        ))
        total_cash_flow = venta_qs.aggregate(t=Sum("total"))["t"] or 0

        top_store_raw = (
            _tienda(_scope(Venta.objects.filter(estado="completada", created_at__date=hoy)))
            .values("tienda_id", "tienda__nombre")
            .annotate(total=Sum("total"))
            .order_by("-total")
            .first()
        )
        top_store = {
            "nombre":    top_store_raw["tienda__nombre"] if top_store_raw else "—",
            "total_hoy": float(top_store_raw["total"])   if top_store_raw else 0.0,
        }

        sesion_qs = _tienda(_scope(
            SesionCaja.objects.filter(
                estado="cerrada", fecha_cierre__gte=inicio_actual, diferencia__lt=0,
            ),
            "tienda__empresa",
        ))
        total_discrepancias  = sesion_qs.aggregate(t=Sum("diferencia"))["t"] or 0
        num_tiendas_con_diff = sesion_qs.values("tienda_id").distinct().count()

        ventas_mes_qs    = _tienda(_scope(Venta.objects.filter(estado="completada", created_at__gte=inicio_mes)))
        total_ventas_mes = ventas_mes_qs.aggregate(t=Sum("total"))["t"] or 0
        total_gastos_mes = (
            _tienda(_scope(Gasto.objects.filter(created_at__gte=inicio_mes), "tienda__empresa"))
            .aggregate(t=Sum("monto"))["t"] or 0
        )
        net_profit = round(float(total_ventas_mes) - float(total_gastos_mes), 2)

        # ── Sales trends + crecimiento (una sola evaluación) ──
        trends_raw = list(
            venta_qs.values("tienda_id", "tienda__nombre")
            .annotate(total=Sum("total"))
            .order_by("-total")
        )
        ventas_por_tienda = [
            {"tienda_id": r["tienda_id"], "nombre": r["tienda__nombre"], "total": float(r["total"] or 0)}
            for r in trends_raw[:10]
        ]
        actuales = {
            r["tienda_id"]: {"nombre": r["tienda__nombre"], "total": float(r["total"] or 0)}
            for r in trends_raw
        }

        anteriores = {
            r["tienda_id"]: float(r["total"] or 0)
            for r in _tienda(_scope(
                Venta.objects.filter(
                    estado="completada",
                    created_at__gte=inicio_ant,
                    created_at__lt=inicio_actual,
                )
            )).values("tienda_id").annotate(total=Sum("total"))
        }

        top_crecimiento = []
        for tid, datos in actuales.items():
            ant = anteriores.get(tid, 0)
            if ant > 0:
                pct = round(((datos["total"] - ant) / ant) * 100, 1)
            elif datos["total"] > 0:
                pct = 100.0
            else:
                pct = 0.0
            top_crecimiento.append({
                "tienda_id":       tid,
                "nombre":          datos["nombre"],
                "total_actual":    datos["total"],
                "total_anterior":  ant,
                "crecimiento_pct": pct,
            })
        top_crecimiento.sort(key=lambda x: x["crecimiento_pct"], reverse=True)
        top_crecimiento = top_crecimiento[:5]

        # ── Alertas de faltantes ──────────────────────────────
        alertas_faltantes = [
            {
                "sesion_id":    s.id,
                "tienda":       s.tienda.nombre,
                "empleado":     (
                    f"{s.empleado.nombre} {s.empleado.apellido}" if s.empleado else "—"
                ),
                "diferencia":   float(s.diferencia),
                "fecha":        s.fecha_apertura.date().isoformat(),
                "fecha_cierre": s.fecha_cierre.isoformat() if s.fecha_cierre else None,
            }
            for s in (
                _tienda(_scope(
                    SesionCaja.objects.filter(estado="cerrada", diferencia__lt=0)
                    .select_related("tienda", "empleado"),
                    "tienda__empresa",
                )).order_by("diferencia")[:20]
            )
        ]

        return Response({
            "periodo": periodo,
            "kpis": {
                "total_cash_flow":          float(total_cash_flow),
                "top_store":                top_store,
                "total_discrepancias":      float(total_discrepancias),
                "num_tiendas_con_faltante": num_tiendas_con_diff,
                "net_profit":               net_profit,
            },
            "ventas_por_tienda": ventas_por_tienda,
            "alertas_faltantes": alertas_faltantes,
            "top_crecimiento":   top_crecimiento,
        })
