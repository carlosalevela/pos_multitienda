from decimal import Decimal
from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Sum

from core.permissions import EsAdminOSupervisor, es_superadmin, get_empresa
from .models import SesionCaja, MovimientoCaja
from .serializers import (
    SesionCajaSerializer, AbrirCajaSerializer, CerrarCajaSerializer
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
                {"error": "Este usuario no tiene una tienda asignada."},
                status=400)

        if not es_superadmin(request):
            empresa = get_empresa(request)
            if request.user.tienda.empresa != empresa:
                return Response(
                    {"error": "La tienda asignada no pertenece a tu empresa."},
                    status=403)

        monto_inicial  = serializer.validated_data["monto_inicial"]
        sesion_abierta = SesionCaja.objects.filter(
            tienda_id=tienda_id, estado="abierta"
        ).first()

        if sesion_abierta:
            return Response({
                "error":      "Ya existe una caja abierta en esta tienda.",
                "sesion_id":  sesion_abierta.id,
                "abierta_por": f"{sesion_abierta.empleado.nombre} "
                               f"{sesion_abierta.empleado.apellido}"
                               if sesion_abierta.empleado else "Desconocido",
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
            if es_superadmin(request):
                sesion = SesionCaja.objects.get(pk=pk)
            else:
                sesion = SesionCaja.objects.get(
                    pk=pk, tienda__empresa=get_empresa(request))
        except SesionCaja.DoesNotExist:
            return Response(
                {"error": "Sesión de caja no encontrada."}, status=404)

        if sesion.estado == "cerrada":
            return Response({"error": "Esta caja ya está cerrada."}, status=400)

        serializer = CerrarCajaSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        monto_real    = serializer.validated_data["monto_final_real"]
        observaciones = serializer.validated_data.get("observaciones", "")

        from ventas.models import Venta
        from contabilidad.models import Gasto
        from devoluciones.models import Devolucion

        # ── Ventas (solo efectivo y mixto entran al cajón) ────
        total_ventas = Venta.objects.filter(
            sesion_caja=sesion, estado="completada",
            metodo_pago__in=["efectivo", "mixto"]
        ).aggregate(t=Sum("total"))["t"] or Decimal("0")

        # ── Gastos (solo efectivo sale del cajón) ─────────────
        total_gastos = Gasto.objects.filter(
            sesion_caja=sesion, metodo_pago="efectivo"
        ).aggregate(t=Sum("monto"))["t"] or Decimal("0")

        # ── Abonos desglosados ────────────────────────────────
        base_a = sesion.movimientos.filter(tipo="abono_separado")

        abonos_efectivo = base_a.filter(
            metodo_pago="efectivo"
        ).aggregate(t=Sum("monto"))["t"] or Decimal("0")

        abonos_tarjeta = base_a.filter(
            metodo_pago="tarjeta"
        ).aggregate(t=Sum("monto"))["t"] or Decimal("0")

        abonos_transferencia = base_a.filter(
            metodo_pago="transferencia"
        ).aggregate(t=Sum("monto"))["t"] or Decimal("0")

        abonos_total = abonos_efectivo + abonos_tarjeta + abonos_transferencia

        # ── Devoluciones ──────────────────────────────────────
        base_d = Devolucion.objects.filter(
            venta__sesion_caja=sesion, estado="procesada")

        dev_efectivo = base_d.filter(
            tipo="devolucion",
            metodo_devolucion="efectivo"
        ).aggregate(t=Sum("total_devuelto"))["t"] or Decimal("0")

        cambios_cobrar = base_d.filter(
            tipo="cambio", tipo_diferencia="cobrar",
            metodo_pago_diferencia="efectivo"
        ).aggregate(t=Sum("diferencia"))["t"] or Decimal("0")

        cambios_devolver = base_d.filter(
            tipo="cambio", tipo_diferencia="devolver",
            metodo_pago_diferencia="efectivo"
        ).aggregate(t=Sum("diferencia"))["t"] or Decimal("0")

        neto_dev_efectivo = dev_efectivo + cambios_devolver - cambios_cobrar

        # ── Cuadre (solo efectivo) ────────────────────────────
        monto_sistema = (
            sesion.monto_inicial
            + total_ventas
            + abonos_efectivo        # ← solo efectivo afecta el cajón
            - total_gastos
            - neto_dev_efectivo
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
            "detail":                    "Caja cerrada correctamente.",
            "sesion_id":                 sesion.id,
            "monto_inicial":             float(sesion.monto_inicial),
            "total_ventas":              float(total_ventas),
            "total_gastos":              float(total_gastos),
            # Abonos desglosados
            "abonos_efectivo":           float(abonos_efectivo),
            "abonos_tarjeta":            float(abonos_tarjeta),
            "abonos_transferencia":      float(abonos_transferencia),
            "abonos_total":              float(abonos_total),
            "total_devoluciones":        float(neto_dev_efectivo),
            "monto_final_sistema":       float(monto_sistema),
            "monto_final_real":          float(monto_real),
            "diferencia":                float(diferencia),
            "estado_diferencia":         "✅ Cuadre exacto" if diferencia == 0
                else f"⚠️ Faltante ${abs(diferencia)}" if diferencia < 0
                else f"💰 Sobrante ${diferencia}",
        })


# ── Sesión activa de una tienda ───────────────────────────────
class SesionActivaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, tienda_id):
        try:
            if es_superadmin(request):
                sesion = SesionCaja.objects.filter(
                    tienda_id=tienda_id, estado="abierta",
                ).select_related("empleado", "tienda").first()
            else:
                sesion = SesionCaja.objects.filter(
                    tienda_id=tienda_id,
                    tienda__empresa=get_empresa(request),
                    estado="abierta",
                ).select_related("empleado", "tienda").first()
        except Exception:
            sesion = None

        if not sesion:
            return Response(
                {"error": "No hay caja abierta en esta tienda."}, status=404)

        return Response(SesionCajaSerializer(
            sesion, context={"request": request}
        ).data)


# ── Historial y detalle ───────────────────────────────────────
class SesionCajaListView(generics.ListAPIView):
    serializer_class   = SesionCajaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = SesionCaja.objects.select_related(
            "empleado", "tienda"
        ).order_by("-fecha_apertura")

        if es_superadmin(self.request):
            empresa_id = self.request.query_params.get("empresa")
            if empresa_id:
                qs = qs.filter(tienda__empresa_id=empresa_id)
        else:
            qs = qs.filter(tienda__empresa=get_empresa(self.request))

        tienda_id = self.request.query_params.get("tienda_id")
        fecha     = self.request.query_params.get("fecha")
        estado    = self.request.query_params.get("estado", "cerrada")

        if tienda_id: qs = qs.filter(tienda_id=tienda_id)
        if fecha:     qs = qs.filter(fecha_apertura__date=fecha)
        qs = qs.filter(estado=estado)
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context


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
        from ventas.models import Venta
        from contabilidad.models import Gasto
        from devoluciones.models import Devolucion

        try:
            if es_superadmin(request):
                sesion = SesionCaja.objects.select_related(
                    "tienda", "empleado"
                ).get(pk=pk, estado="abierta")
            else:
                sesion = SesionCaja.objects.select_related(
                    "tienda", "empleado"
                ).get(pk=pk, estado="abierta",
                      tienda__empresa=get_empresa(request))
        except SesionCaja.DoesNotExist:
            return Response(
                {"error": "Sesión no encontrada o ya cerrada."}, status=404)

        def agg(qs):   return qs.aggregate(t=Sum("monto"))["t"]          or Decimal("0")
        def vsum(qs):  return qs.aggregate(t=Sum("total"))["t"]          or Decimal("0")
        def dsum(qs):  return qs.aggregate(t=Sum("total_devuelto"))["t"] or Decimal("0")
        def ddsum(qs): return qs.aggregate(t=Sum("diferencia"))["t"]     or Decimal("0")

        base_v = Venta.objects.filter(sesion_caja=sesion, estado="completada")
        base_g = Gasto.objects.filter(sesion_caja=sesion)
        base_d = Devolucion.objects.filter(
            venta__sesion_caja=sesion, estado="procesada")

        # Ventas
        v_efectivo      = vsum(base_v.filter(metodo_pago="efectivo"))
        v_tarjeta       = vsum(base_v.filter(metodo_pago="tarjeta"))
        v_transferencia = vsum(base_v.filter(metodo_pago="transferencia"))
        v_mixto         = vsum(base_v.filter(metodo_pago="mixto"))
        total_ventas    = v_efectivo + v_tarjeta + v_transferencia + v_mixto
        num_transacciones = base_v.count()

        # Gastos
        g_efectivo     = agg(base_g.filter(metodo_pago="efectivo"))
        g_otros        = agg(base_g.exclude(metodo_pago="efectivo"))
        total_g        = g_efectivo + g_otros
        detalle_gastos = list(base_g.values("categoria", "monto", "metodo_pago"))

        # Abonos desglosados
        base_a          = sesion.movimientos.filter(tipo="abono_separado")
        a_efectivo      = agg(base_a.filter(metodo_pago="efectivo"))
        a_transferencia = agg(base_a.filter(metodo_pago="transferencia"))
        a_tarjeta       = agg(base_a.filter(metodo_pago="tarjeta"))
        total_abonos    = a_efectivo + a_transferencia + a_tarjeta
        num_abonos      = base_a.count()

        # Devoluciones
        dev_efectivo     = dsum(base_d.filter(
            tipo="devolucion", metodo_devolucion="efectivo"))
        cambios_cobrar   = ddsum(base_d.filter(
            tipo="cambio", tipo_diferencia="cobrar",
            metodo_pago_diferencia="efectivo"))
        cambios_devolver = ddsum(base_d.filter(
            tipo="cambio", tipo_diferencia="devolver",
            metodo_pago_diferencia="efectivo"))
        neto_dev_efectivo = dev_efectivo + cambios_devolver - cambios_cobrar
        num_devoluciones  = base_d.count()

        # Monto esperado (solo efectivo afecta el cajón)
        monto_esperado = (
            sesion.monto_inicial
            + v_efectivo + v_mixto
            + a_efectivo             # ← solo efectivo
            - g_efectivo
            - neto_dev_efectivo
        )

        nombre = f"{sesion.empleado.nombre} {sesion.empleado.apellido}" \
            if sesion.empleado else ""

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
                "num_transacciones": num_transacciones,
            },
            "gastos": {
                "efectivo": float(g_efectivo),
                "otros":    float(g_otros),
                "total":    float(total_g),
                "detalle":  detalle_gastos,
            },
            "abonos": {
                "efectivo":      float(a_efectivo),
                "transferencia": float(a_transferencia),
                "tarjeta":       float(a_tarjeta),
                "total":         float(total_abonos),
                "cantidad":      num_abonos,
            },
            "devoluciones": {
                "efectivo":          float(dev_efectivo),
                "cambios_cobrar":    float(cambios_cobrar),
                "cambios_devolver":  float(cambios_devolver),
                "neto_efectivo":     float(neto_dev_efectivo),
                "cantidad":          num_devoluciones,
                "cambios_producto":  base_d.filter(
                    tipo="cambio",
                    producto_reemplazo__isnull=False
                ).count(),
            },
            "monto_esperado_caja": float(monto_esperado),
        })