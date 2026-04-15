from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Empleado
from .serializers import EmpleadoSerializer, CrearEmpleadoSerializer, CustomTokenSerializer


# ── Permisos ───────────────────────────────────────────────────

class EsAdmin(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.rol == "admin"


# ── Helper empresa ─────────────────────────────────────────────

def _get_empresa(request):
    return request.user.empresa


# ── Auth ───────────────────────────────────────────────────────

class LoginView(TokenObtainPairView):
    permission_classes = [AllowAny]
    serializer_class   = CustomTokenSerializer


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            token = RefreshToken(request.data["refresh"])
            token.blacklist()
            return Response({"detail": "Sesión cerrada correctamente."}, status=200)
        except Exception:
            return Response({"error": "Token inválido."}, status=400)


# ── Perfil propio ──────────────────────────────────────────────

class MiPerfilView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = EmpleadoSerializer(request.user, context={"request": request})
        return Response(serializer.data)

    def patch(self, request):
        # ✅ campos que un empleado puede editar de sí mismo
        CAMPOS_PERMITIDOS = {"nombre", "apellido", "telefono", "email"}
        data = {k: v for k, v in request.data.items() if k in CAMPOS_PERMITIDOS}

        serializer = EmpleadoSerializer(
            request.user, data=data, partial=True,
            context={"request": request},
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)


# ── Empleados (gestión por admin) ──────────────────────────────

class EmpleadoListCreateView(generics.ListCreateAPIView):
    permission_classes = [EsAdmin]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return CrearEmpleadoSerializer
        return EmpleadoSerializer

    def get_queryset(self):
        # ✅ solo empleados de la empresa del admin
        return Empleado.objects.filter(
            activo=True,
            empresa=_get_empresa(self.request),
        ).select_related("tienda", "empresa")

    def perform_create(self, serializer):
        # ✅ inyecta empresa automáticamente — nunca viene del body
        serializer.save(empresa=_get_empresa(self.request))

    def get_serializer_context(self):
        # ✅ context necesario para validate_tienda en CrearEmpleadoSerializer
        context = super().get_serializer_context()
        context["request"] = self.request
        return context


class EmpleadoDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [EsAdmin]

    def get_serializer_class(self):
        if self.request.method in ["PUT", "PATCH"]:
            return CrearEmpleadoSerializer
        return EmpleadoSerializer

    def get_queryset(self):
        # ✅ scoped — no puede editar empleados de otras empresas
        return Empleado.objects.filter(
            empresa=_get_empresa(self.request)
        ).select_related("tienda", "empresa")

    def get_serializer_context(self):
        # ✅ context necesario para validate_tienda al actualizar
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def destroy(self, request, *args, **kwargs):
        empleado = self.get_object()
        empleado.activo = False
        empleado.save()
        return Response({"detail": "Empleado desactivado."}, status=200)


# ── Cambiar contraseña ─────────────────────────────────────────

class CambiarPasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user     = request.user
        old_pass = request.data.get("password_actual")
        new_pass = request.data.get("password_nuevo")

        if not user.check_password(old_pass):
            return Response({"error": "Contraseña actual incorrecta."}, status=400)
        if not new_pass or len(new_pass) < 6:
            return Response({"error": "Mínimo 6 caracteres."}, status=400)

        user.set_password(new_pass)
        user.save()
        return Response({"detail": "Contraseña actualizada correctamente."})