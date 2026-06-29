from decimal import Decimal

from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import serializers

from core.permissions import es_superadmin, get_empresa
from .models import SesionCaja


# ── Serializer ligero para listas (evita N+1) ─────────────────
class SesionCajaResumenSerializer(serializers.ModelSerializer):
    """Usado en SesionCajaListView. Los totales vienen de anotaciones en el QS."""

    empleado_nombre = serializers.SerializerMethodField()
    tienda_nombre   = serializers.CharField(source="tienda.nombre", read_only=True)
    saldo_inicial   = serializers.DecimalField(
        source="monto_inicial", max_digits=12, decimal_places=2, read_only=True
    )
    ventas_total = serializers.DecimalField(
        source="ventas_total_ann", max_digits=12, decimal_places=2, read_only=True
    )
    gastos_total = serializers.DecimalField(
        source="gastos_total_ann", max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model  = SesionCaja
        fields = [
            "id", "tienda", "tienda_nombre",
            "empleado", "empleado_nombre",
            "fecha_apertura", "fecha_cierre",
            "saldo_inicial",
            "monto_final_sistema", "monto_final_real",
            "diferencia", "observaciones", "estado",
            "ventas_total", "gastos_total",
        ]

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f"{obj.empleado.nombre} {obj.empleado.apellido}"
        return None

    @staticmethod
    def anotaciones():
        """QuerySet annotations requeridas por este serializer."""
        _zero = Value(Decimal("0"), output_field=DecimalField())
        return {
            "ventas_total_ann": Coalesce(
                Sum("ventas__total", filter=Q(ventas__estado="completada")),
                _zero,
            ),
            "gastos_total_ann": Coalesce(Sum("gasto__monto"), _zero),
        }


# ── Serializer completo para detalle / sesión activa ──────────
class SesionCajaSerializer(serializers.ModelSerializer):
    empleado_nombre       = serializers.SerializerMethodField()
    tienda_nombre         = serializers.CharField(source="tienda.nombre", read_only=True)
    saldo_inicial         = serializers.DecimalField(
        source="monto_inicial", max_digits=12, decimal_places=2, read_only=True
    )
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
    abonos_efectivo       = serializers.SerializerMethodField()
    abonos_tarjeta        = serializers.SerializerMethodField()
    abonos_transferencia  = serializers.SerializerMethodField()
    abonos_total          = serializers.SerializerMethodField()
    num_abonos            = serializers.SerializerMethodField()
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
        if request and not es_superadmin(request):
            if tienda.empresa != get_empresa(request):
                raise serializers.ValidationError("La tienda no pertenece a tu empresa.")
        return tienda

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f"{obj.empleado.nombre} {obj.empleado.apellido}"
        return None

    # ── Ventas ────────────────────────────────────────────────

    def _vsum(self, obj, metodo=None):
        from ventas.models import Venta
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
        return Venta.objects.filter(sesion_caja=obj, estado="completada").count()

    # ── Gastos ────────────────────────────────────────────────

    def get_gastos_total(self, obj):
        from contabilidad.models import Gasto
        return float(
            Gasto.objects.filter(sesion_caja=obj)
            .aggregate(t=Sum("monto"))["t"] or 0
        )

    # ── Abonos ────────────────────────────────────────────────

    def _asum(self, obj, metodo=None):
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

    def _dev_efectivo_neto(self, obj) -> Decimal:
        """Neto de devoluciones en efectivo para esta sesión.

        Cacheado en la instancia del serializer para evitar repetir las 3
        queries cuando tanto `devoluciones_efectivo` como `monto_esperado`
        lo necesitan en la misma serialización.
        """
        if not hasattr(self, "_dev_ef_cache"):
            from devoluciones.models import Devolucion
            base = Devolucion.objects.filter(
                venta__sesion_caja=obj, estado="procesada"
            )
            dev      = base.filter(
                tipo="devolucion", metodo_devolucion="efectivo",
            ).aggregate(t=Sum("total_devuelto"))["t"] or 0

            cobrar   = base.filter(
                tipo="cambio", tipo_diferencia="cobrar",
                metodo_pago_diferencia="efectivo",
            ).aggregate(t=Sum("diferencia"))["t"] or 0

            devolver = base.filter(
                tipo="cambio", tipo_diferencia="devolver",
                metodo_pago_diferencia="efectivo",
            ).aggregate(t=Sum("diferencia"))["t"] or 0

            self._dev_ef_cache = Decimal(str(dev + devolver - cobrar))
        return self._dev_ef_cache

    def get_devoluciones_efectivo(self, obj):
        return float(self._dev_efectivo_neto(obj))

    def get_num_devoluciones(self, obj):
        from devoluciones.models import Devolucion
        return Devolucion.objects.filter(
            venta__sesion_caja=obj, estado="procesada"
        ).count()

    def get_num_cambios_producto(self, obj):
        from devoluciones.models import Devolucion
        return Devolucion.objects.filter(
            venta__sesion_caja=obj, estado="procesada",
            tipo="cambio", producto_reemplazo__isnull=False,
        ).count()

    # ── Monto esperado ────────────────────────────────────────

    def get_monto_esperado(self, obj):
        from ventas.models import Venta
        from contabilidad.models import Gasto

        def vsum(qs): return qs.aggregate(t=Sum("total"))["t"] or 0
        def agg(qs):  return qs.aggregate(t=Sum("monto"))["t"]  or 0

        base_v = Venta.objects.filter(sesion_caja=obj, estado="completada")
        v_ef   = vsum(base_v.filter(metodo_pago="efectivo"))
        v_mx   = vsum(base_v.filter(metodo_pago="mixto"))
        g_ef   = agg(Gasto.objects.filter(sesion_caja=obj, metodo_pago="efectivo"))
        a_ef   = agg(obj.movimientos.filter(tipo="abono_separado", metodo_pago="efectivo"))
        dev_ef = self._dev_efectivo_neto(obj)   # reutiliza el resultado cacheado
        return float(obj.monto_inicial + v_ef + v_mx + a_ef - g_ef - dev_ef)


class AbrirCajaSerializer(serializers.Serializer):
    monto_inicial = serializers.DecimalField(max_digits=12, decimal_places=2)


class CerrarCajaSerializer(serializers.Serializer):
    monto_final_real = serializers.DecimalField(max_digits=12, decimal_places=2)
    observaciones    = serializers.CharField(required=False, allow_blank=True)
