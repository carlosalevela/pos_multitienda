from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from core.permissions import es_superadmin, get_empresa
from .models import Empleado


class EmpleadoSerializer(serializers.ModelSerializer):
    tienda_nombre = serializers.CharField(source="tienda.nombre", read_only=True)
    empresa_nombre = serializers.CharField(source="empresa.nombre", read_only=True)

    class Meta:
        model = Empleado
        fields = [
            "id",
            "nombre",
            "apellido",
            "cedula",
            "email",
            "rol",
            "activo",
            "tienda",
            "tienda_nombre",
            "empresa",
            "empresa_nombre",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "empresa"]


class CrearEmpleadoSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = Empleado
        fields = [
            "nombre",
            "apellido",
            "cedula",
            "email",
            "password",
            "rol",
            "tienda",
            "empresa",
        ]
        extra_kwargs = {
            "empresa": {"read_only": True},
        }

    def validate(self, attrs):
        request = self.context.get("request")
        tienda = attrs.get("tienda")

        if not request or not tienda:
            return attrs

        if es_superadmin(request):
            empresa_id = request.data.get("empresa")
            if not empresa_id:
                raise serializers.ValidationError({
                    "empresa": "El superadmin debe enviar empresa."
                })

            if str(tienda.empresa_id) != str(empresa_id):
                raise serializers.ValidationError({
                    "tienda": "La tienda no pertenece a la empresa seleccionada."
                })
        else:
            empresa = get_empresa(request)
            if tienda.empresa_id != empresa.id:
                raise serializers.ValidationError({
                    "tienda": "La tienda no pertenece a tu empresa."
                })

        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        empleado = Empleado(**validated_data)
        empleado.set_password(password)
        empleado.save()
        return empleado


class CustomTokenSerializer(TokenObtainPairSerializer):
    """JWT con datos extra del empleado en el token"""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["nombre"] = user.nombre
        token["apellido"] = user.apellido
        token["rol"] = user.rol
        token["tienda_id"] = user.tienda_id
        token["tienda_nombre"] = user.tienda.nombre if user.tienda else ""
        token["empresa_id"] = user.empresa_id
        token["empresa_nombre"] = user.empresa.nombre if user.empresa else ""
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        empleado = self.user
        data["empleado"] = {
            "id": empleado.id,
            "nombre": empleado.nombre,
            "apellido": empleado.apellido,
            "email": empleado.email,
            "rol": empleado.rol,
            "tienda_id": empleado.tienda_id,
            "tienda_nombre": empleado.tienda.nombre if empleado.tienda else "",
            "empresa_id": empleado.empresa_id,
            "empresa_nombre": empleado.empresa.nombre if empleado.empresa else "",
        }
        return data