from decimal import Decimal
from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Sum

from .models import SesionCaja
from .serializers import SesionCajaSerializer, AbrirCajaSerializer, CerrarCajaSerializer


class EsAdminOSupervisor(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.rol in ["admin", "supervisor"]


# ── Abrir caja ────────────────────────────────────────────────
# caja/views.py
class AbrirCajaView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AbrirCajaSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        # ✅ Tienda viene del usuario autenticado, no del body
        tienda_id = request.user.tienda_id
        if not tienda_id:
            return Response(
                {"error": "Este usuario no tiene una tienda asignada."},
                status=400
            )

        monto_inicial = serializer.validated_data["monto_inicial"]

        sesion_abierta = SesionCaja.objects.filter(
            tienda_id=tienda_id, estado="abierta"
        ).first()

        if sesion_abierta:
            return Response({
                "error":      "Ya existe una caja abierta en esta tienda.",
                "sesion_id":  sesion_abierta.id,
                "abierta_por": f"{sesion_abierta.empleado.nombre} {sesion_abierta.empleado.apellido}"
                               if sesion_abierta.empleado else "Desconocido",
                "desde":      sesion_abierta.fecha_apertura,
            }, status=400)

        sesion = SesionCaja.objects.create(
            tienda_id     = tienda_id,
            empleado      = request.user,
            monto_inicial = monto_inicial,
            estado        = "abierta",
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
            sesion = SesionCaja.objects.get(pk=pk)
        except SesionCaja.DoesNotExist:
            return Response({"error": "Sesión de caja no encontrada."}, status=404)

        if sesion.estado == "cerrada":
            return Response({"error": "Esta caja ya está cerrada."}, status=400)

        serializer = CerrarCajaSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        monto_real    = serializer.validated_data["monto_final_real"]
        observaciones = serializer.validated_data.get("observaciones", "")

        from ventas.models import Venta
        from contabilidad.models import Gasto

        total_ventas = Venta.objects.filter(
            sesion_caja=sesion, estado="completada",
            metodo_pago__in=["efectivo", "mixto"]
        ).aggregate(t=Sum("total"))["t"] or Decimal("0")

        total_gastos = Gasto.objects.filter(
            sesion_caja=sesion, metodo_pago="efectivo"
        ).aggregate(t=Sum("monto"))["t"] or Decimal("0")

        monto_sistema = sesion.monto_inicial + total_ventas - total_gastos
        diferencia    = monto_real - monto_sistema

        sesion.monto_final_sistema = monto_sistema
        sesion.monto_final_real    = monto_real
        sesion.diferencia          = diferencia
        sesion.observaciones       = observaciones
        sesion.estado              = "cerrada"
        sesion.fecha_cierre        = timezone.now()
        sesion.save()

        return Response({
            "detail":              "Caja cerrada correctamente.",
            "sesion_id":           sesion.id,
            "monto_inicial":       float(sesion.monto_inicial),
            "total_ventas":        float(total_ventas),
            "total_gastos":        float(total_gastos),
            "monto_final_sistema": float(monto_sistema),
            "monto_final_real":    float(monto_real),
            "diferencia":          float(diferencia),
            "estado_diferencia":   "✅ Cuadre exacto" if diferencia == 0
                                   else f"⚠️ Faltante ${abs(diferencia)}" if diferencia < 0
                                   else f"💰 Sobrante ${diferencia}",
        })


# ── Sesión activa de una tienda ───────────────────────────────
class SesionActivaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, tienda_id):
        sesion = SesionCaja.objects.filter(
            tienda_id=tienda_id, estado="abierta"
        ).select_related("empleado", "tienda").first()

        if not sesion:
            return Response({"error": "No hay caja abierta en esta tienda."}, status=404)

        return Response(SesionCajaSerializer(sesion).data)


# ── Historial y detalle ───────────────────────────────────────
class SesionCajaListView(generics.ListAPIView):
    serializer_class   = SesionCajaSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        qs        = SesionCaja.objects.select_related("empleado","tienda").order_by("-fecha_apertura")
        tienda_id = self.request.query_params.get("tienda_id")
        estado    = self.request.query_params.get("estado")
        fecha     = self.request.query_params.get("fecha")
        if tienda_id: qs = qs.filter(tienda_id=tienda_id)
        if estado:    qs = qs.filter(estado=estado)
        if fecha:     qs = qs.filter(fecha_apertura__date=fecha)
        return qs

class SesionCajaDetailView(generics.RetrieveAPIView):
    queryset           = SesionCaja.objects.select_related("empleado","tienda")
    serializer_class   = SesionCajaSerializer
    permission_classes = [IsAuthenticated]

# ── Resumen pre-cierre ────────────────────────────────
class ResumenCierreView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from ventas.models import Venta
        from contabilidad.models import Gasto

        try:
            sesion = SesionCaja.objects.select_related(
                'tienda', 'empleado').get(pk=pk, estado='abierta')
        except SesionCaja.DoesNotExist:
            return Response(
                {"error": "Sesión no encontrada o ya cerrada."}, status=404)

        def agg(qs): return qs.aggregate(t=Sum('monto'))['t'] or Decimal('0')
        def vsum(qs): return qs.aggregate(t=Sum('total'))['t'] or Decimal('0')

        base_v = Venta.objects.filter(sesion_caja=sesion, estado='completada')
        base_g = Gasto.objects.filter(sesion_caja=sesion)

        v_efectivo       = vsum(base_v.filter(metodo_pago='efectivo'))
        v_tarjeta        = vsum(base_v.filter(metodo_pago='tarjeta'))
        v_transferencia  = vsum(base_v.filter(metodo_pago='transferencia'))
        v_mixto          = vsum(base_v.filter(metodo_pago='mixto'))
        total_ventas     = v_efectivo + v_tarjeta + v_transferencia + v_mixto
        num_transacciones = base_v.count()

        g_efectivo = agg(base_g.filter(metodo_pago='efectivo'))
        g_otros    = agg(base_g.exclude(metodo_pago='efectivo'))
        total_g    = g_efectivo + g_otros

        detalle_gastos = list(base_g.values('categoria', 'monto', 'metodo_pago'))

        monto_esperado = sesion.monto_inicial + v_efectivo + v_mixto - g_efectivo

        nombre = ''
        if sesion.empleado:
            nombre = f"{sesion.empleado.nombre} {sesion.empleado.apellido}"

        return Response({
            'sesion_id':       sesion.id,
            'tienda_nombre':   sesion.tienda.nombre,
            'empleado_nombre': nombre,
            'fecha_apertura':  sesion.fecha_apertura,
            'monto_inicial':   float(sesion.monto_inicial),
            'ventas': {
                'efectivo':          float(v_efectivo),
                'tarjeta':           float(v_tarjeta),
                'transferencia':     float(v_transferencia),
                'mixto':             float(v_mixto),
                'total':             float(total_ventas),
                'num_transacciones': num_transacciones,
            },
            'gastos': {
                'efectivo': float(g_efectivo),
                'otros':    float(g_otros),
                'total':    float(total_g),
                'detalle':  detalle_gastos,
            },
            'monto_esperado_caja': float(monto_esperado),
        })