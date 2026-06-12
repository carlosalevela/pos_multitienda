from rest_framework import serializers
from .models import SesionCaja
from decimal import Decimal


class SesionCajaSerializer(serializers.ModelSerializer):
    empleado_nombre       = serializers.SerializerMethodField()
    tienda_nombre         = serializers.CharField(source="tienda.nombre", read_only=True)
    saldo_inicial         = serializers.DecimalField(
                                source='monto_inicial', max_digits=12,
                                decimal_places=2, read_only=True)
    ventas_total          = serializers.SerializerMethodField()
    ventas_efectivo       = serializers.SerializerMethodField()
    ventas_tarjeta        = serializers.SerializerMethodField()
    ventas_transferencia  = serializers.SerializerMethodField()
    ventas_mixto          = serializers.SerializerMethodField()
    num_transacciones     = serializers.SerializerMethodField()
    gastos_total          = serializers.SerializerMethodField()
    devoluciones_efectivo = serializers.SerializerMethodField()
    num_devoluciones      = serializers.SerializerMethodField()
    num_cambios_producto  = serializers.SerializerMethodField()
    # ── Abonos desglosados ────────────────────────────────────
    abonos_efectivo       = serializers.SerializerMethodField()
    abonos_tarjeta        = serializers.SerializerMethodField()
    abonos_transferencia  = serializers.SerializerMethodField()
    abonos_total          = serializers.SerializerMethodField()
    num_abonos            = serializers.SerializerMethodField()
    # ─────────────────────────────────────────────────────────
    monto_esperado        = serializers.SerializerMethodField()

    class Meta:
        model  = SesionCaja
        fields = [
            "id", "tienda", "tienda_nombre",
            "empleado", "empleado_nombre",
            "fecha_apertura", "fecha_cierre",
            "saldo_inicial",
            "monto_final_sistema", "monto_final_real",
            "diferencia", "observaciones", "estado",
            "ventas_total", "ventas_efectivo", "ventas_tarjeta",
            "ventas_transferencia", "ventas_mixto",
            "num_transacciones", "gastos_total",
            "devoluciones_efectivo", "num_devoluciones",
            "num_cambios_producto",
            "abonos_efectivo", "abonos_tarjeta",
            "abonos_transferencia", "abonos_total", "num_abonos",
            "monto_esperado",
        ]
        read_only_fields = [
            "id", "empleado", "fecha_apertura", "fecha_cierre",
            "monto_final_sistema", "diferencia", "estado",
        ]

    def validate_tienda(self, tienda):
        request = self.context.get("request")
        if request and tienda.empresa != request.user.empresa:
            raise serializers.ValidationError(
                "La tienda no pertenece a tu empresa.")
        return tienda

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f"{obj.empleado.nombre} {obj.empleado.apellido}"
        return None

    # ── Ventas ────────────────────────────────────────────────

    def _vsum(self, obj, metodo=None):
        from ventas.models import Venta
        from django.db.models import Sum
        qs = Venta.objects.filter(sesion_caja=obj, estado="completada")
        if metodo:
            qs = qs.filter(metodo_pago=metodo)
        return float(qs.aggregate(t=Sum("total"))["t"] or 0)

    def get_ventas_total(self, obj):         return self._vsum(obj)
    def get_ventas_efectivo(self, obj):      return self._vsum(obj, "efectivo")
    def get_ventas_tarjeta(self, obj):       return self._vsum(obj, "tarjeta")
    def get_ventas_transferencia(self, obj): return self._vsum(obj, "transferencia")
    def get_ventas_mixto(self, obj):         return self._vsum(obj, "mixto")

    def get_num_transacciones(self, obj):
        from ventas.models import Venta
        return Venta.objects.filter(
            sesion_caja=obj, estado="completada").count()

    # ── Gastos ────────────────────────────────────────────────

    def get_gastos_total(self, obj):
        from contabilidad.models import Gasto
        from django.db.models import Sum
        return float(Gasto.objects.filter(
            sesion_caja=obj
        ).aggregate(t=Sum("monto"))["t"] or 0)

    # ── Abonos ────────────────────────────────────────────────

    def _asum(self, obj, metodo=None):
        from django.db.models import Sum
        qs = obj.movimientos.filter(tipo="abono_separado")
        if metodo:
            qs = qs.filter(metodo_pago=metodo)
        return float(qs.aggregate(t=Sum("monto"))["t"] or 0)

    def get_abonos_efectivo(self, obj):      return self._asum(obj, "efectivo")
    def get_abonos_tarjeta(self, obj):       return self._asum(obj, "tarjeta")
    def get_abonos_transferencia(self, obj): return self._asum(obj, "transferencia")
    def get_abonos_total(self, obj):         return self._asum(obj)
    def get_num_abonos(self, obj):
        return obj.movimientos.filter(tipo="abono_separado").count()

    # ── Devoluciones ──────────────────────────────────────────

    def get_devoluciones_efectivo(self, obj):
        from devoluciones.models import Devolucion
        from django.db.models import Sum
        dev = Devolucion.objects.filter(
            venta__sesion_caja=obj, estado="procesada",
            tipo="devolucion",
            metodo_devolucion="efectivo"
        ).aggregate(t=Sum("total_devuelto"))["t"] or 0

        cambios_cobrar = Devolucion.objects.filter(
            venta__sesion_caja=obj, estado="procesada",
            tipo="cambio", tipo_diferencia="cobrar",
            metodo_pago_diferencia="efectivo"
        ).aggregate(t=Sum("diferencia"))["t"] or 0

        cambios_devolver = Devolucion.objects.filter(
            venta__sesion_caja=obj, estado="procesada",
            tipo="cambio", tipo_diferencia="devolver",
            metodo_pago_diferencia="efectivo"
        ).aggregate(t=Sum("diferencia"))["t"] or 0

        return float(dev + cambios_devolver - cambios_cobrar)

    def get_num_devoluciones(self, obj):
        from devoluciones.models import Devolucion
        return Devolucion.objects.filter(
            venta__sesion_caja=obj, estado="procesada"
        ).count()

    def get_num_cambios_producto(self, obj):
        from devoluciones.models import Devolucion
        return Devolucion.objects.filter(
            venta__sesion_caja=obj, estado="procesada",
            tipo="cambio", producto_reemplazo__isnull=False
        ).count()

    # ── Monto esperado ────────────────────────────────────────

    def get_monto_esperado(self, obj):
        from ventas.models import Venta
        from contabilidad.models import Gasto
        from django.db.models import Sum
        def vsum(qs): return qs.aggregate(t=Sum("total"))["t"] or 0
        def agg(qs):  return qs.aggregate(t=Sum("monto"))["t"]  or 0
        base_v = Venta.objects.filter(sesion_caja=obj, estado="completada")
        v_ef   = vsum(base_v.filter(metodo_pago="efectivo"))
        v_mx   = vsum(base_v.filter(metodo_pago="mixto"))
        g_ef   = agg(Gasto.objects.filter(
                     sesion_caja=obj, metodo_pago="efectivo"))
        a_ef   = agg(obj.movimientos.filter(
                     tipo="abono_separado", metodo_pago="efectivo"))
        dev_ef = Decimal(str(self.get_devoluciones_efectivo(obj)))
        return float(obj.monto_inicial + v_ef + v_mx + a_ef - g_ef - dev_ef)


class AbrirCajaSerializer(serializers.Serializer):
    monto_inicial = serializers.DecimalField(max_digits=12, decimal_places=2)


class CerrarCajaSerializer(serializers.Serializer):
    monto_final_real = serializers.DecimalField(max_digits=12, decimal_places=2)
    observaciones    = serializers.CharField(required=False, allow_blank=True)