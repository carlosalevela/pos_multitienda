from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import Empleado


class EmpleadoSerializer(serializers.ModelSerializer):
    tienda_nombre  = serializers.CharField(source="tienda.nombre",  read_only=True)
    empresa_nombre = serializers.CharField(source="empresa.nombre", read_only=True)  # ✅

    class Meta:
        model = Empleado
        fields = [
            "id", "nombre", "apellido", "cedula",
            "email", "rol", "activo",
            "tienda", "tienda_nombre",
            "empresa", "empresa_nombre",            # ✅
            "created_at"
        ]
        read_only_fields = ["id", "created_at", "empresa"]  # ✅ empresa no modificable desde body


class CrearEmpleadoSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = Empleado
        fields = [
            "nombre", "apellido", "cedula",
            "email", "password", "rol",
            "tienda", "empresa",                    # ✅ empresa requerida al crear
        ]
        extra_kwargs = {
            "empresa": {"read_only": True},         # ✅ se inyecta desde la view, no del body
        }

    def validate_tienda(self, tienda):
        """La tienda asignada debe ser de la misma empresa."""  # ✅
        request = self.context.get("request")
        if request and tienda and tienda.empresa != request.user.empresa:
            raise serializers.ValidationError(
                "La tienda no pertenece a tu empresa.")
        return tienda

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
        token["nombre"]        = user.nombre
        token["apellido"]      = user.apellido
        token["rol"]           = user.rol
        token["tienda_id"]     = user.tienda_id
        token["tienda_nombre"] = user.tienda.nombre if user.tienda else ""
        token["empresa_id"]    = user.empresa_id    # ✅ crítico para el frontend
        token["empresa_nombre"] = user.empresa.nombre if user.empresa else ""  # ✅
        return token

    def validate(self, attrs):
        data     = super().validate(attrs)
        empleado = self.user
        data["empleado"] = {
            "id":             empleado.id,
            "nombre":         empleado.nombre,
            "apellido":       empleado.apellido,
            "email":          empleado.email,
            "rol":            empleado.rol,
            "tienda_id":      empleado.tienda_id,
            "tienda_nombre":  empleado.tienda.nombre  if empleado.tienda   else "",
            "empresa_id":     empleado.empresa_id,    # ✅
            "empresa_nombre": empleado.empresa.nombre if empleado.empresa  else "",  # ✅
        }
        return data