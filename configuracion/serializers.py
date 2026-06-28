from rest_framework import serializers
from .models import ConfigTienda, ConfigImpresion

METODOS_VALIDOS = {"efectivo", "tarjeta", "transferencia", "mixto"}


class ConfigTiendaSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ConfigTienda
        fields = [
            "id", "tienda",
            "moneda_simbolo", "moneda_codigo",
            "iva_pct",
            "metodos_pago",
            "habilitar_mayoreo", "umbral_mayoreo",
            "abono_minimo_pct", "dias_max_liquidar",
            "politica_cancelacion", "dias_alerta_separados",
            "updated_at",
        ]
        read_only_fields = ["id", "tienda", "updated_at"]

    def validate_metodos_pago(self, value):
        if not isinstance(value, list) or not value:
            raise serializers.ValidationError(
                "Debe ser una lista con al menos un método de pago."
            )
        invalidos = set(value) - METODOS_VALIDOS
        if invalidos:
            raise serializers.ValidationError(
                f"Métodos no válidos: {invalidos}. Usa: {METODOS_VALIDOS}"
            )
        return value

    def validate_iva_pct(self, value):
        if value < 0 or value > 100:
            raise serializers.ValidationError("El IVA debe estar entre 0 y 100.")
        return value

    def validate_abono_minimo_pct(self, value):
        if value < 0 or value > 100:
            raise serializers.ValidationError(
                "El abono mínimo debe ser un porcentaje entre 0 y 100."
            )
        return value


class ConfigImpresionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ConfigImpresion
        fields = [
            "id", "tienda",
            "tipo_papel", "copias",
            "mostrar_logo", "mostrar_nit",
            "mensaje_pie", "nombre_dispositivo",
            "updated_at",
        ]
        read_only_fields = ["id", "tienda", "updated_at"]

    def validate_copias(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError("El número de copias debe estar entre 1 y 5.")
        return value
