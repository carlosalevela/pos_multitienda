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
            "activo",
            "tienda",
            "empresa",
        ]
        extra_kwargs = {
            "empresa": {"read_only": True},
        }

    def validate(self, attrs):
        request = self.context.get("request")
        tienda = attrs.get("tienda")
        rol    = attrs.get("rol")

        if rol == "superadmin" and not es_superadmin(request):
            raise serializers.ValidationError({
                "rol": "No puedes asignar el rol de superadmin."
            })

        if rol == "cajero" and not tienda:
            raise serializers.ValidationError({
                "tienda": "Un cajero debe tener una tienda asignada."
            })

        if not request or not tienda:
            return attrs

        if es_superadmin(request):
            empresa_id = request.data.get("empresa")
            # En edición parcial, usar la empresa existente del empleado como fallback
            if not empresa_id and self.instance:
                empresa_id = self.instance.empresa_id
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

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class CustomTokenSerializer(TokenObtainPairSerializer):
    """JWT con datos extra del empleado en el token. Acepta email o cédula."""

    def validate(self, attrs):
        identificador = attrs.get("email", "").strip()

        if identificador and "@" not in identificador:
            # Sin '@' → asumir cédula
            empleados = Empleado.objects.filter(
                cedula=identificador, activo=True
            )
            count = empleados.count()
            if count == 0:
                raise serializers.ValidationError(
                    {"email": "No se encontró un usuario activo con esa cédula."}
                )
            if count > 1:
                raise serializers.ValidationError(
                    {"email": "Cédula ambigua. Usa tu correo electrónico para ingresar."}
                )
            attrs["email"] = empleados.first().email

        return super().validate(attrs)

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["nombre"] = user.nombre
        token["apellido"] = user.apellido
        token["rol"] = user.rol
        token["tienda_id"] = user.tienda_id
        token["tienda_nombre"] = user.tienda.nombre if user.tienda else ""
        # Fallback: si empresa no está asignada directamente, inferir desde tienda
        empresa_id = user.empresa_id
        if not empresa_id and user.tienda_id:
            empresa_id = user.tienda.empresa_id
        token["empresa_id"] = empresa_id
        token["empresa_nombre"] = (
            user.empresa.nombre if user.empresa else
            (user.tienda.empresa.nombre if user.tienda and user.tienda.empresa else "")
        )
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        empleado = self.user
        empresa_id = empleado.empresa_id
        if not empresa_id and empleado.tienda_id:
            empresa_id = empleado.tienda.empresa_id
        empresa_nombre = (
            empleado.empresa.nombre if empleado.empresa else
            (empleado.tienda.empresa.nombre if empleado.tienda and empleado.tienda.empresa else "")
        )
        data["empleado"] = {
            "id": empleado.id,
            "nombre": empleado.nombre,
            "apellido": empleado.apellido,
            "email": empleado.email,
            "rol": empleado.rol,
            "tienda_id": empleado.tienda_id,
            "tienda_nombre": empleado.tienda.nombre if empleado.tienda else "",
            "empresa_id": empresa_id,
            "empresa_nombre": empresa_nombre,
        }
        return data