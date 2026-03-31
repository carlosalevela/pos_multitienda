from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Empleado
from .serializers import EmpleadoSerializer, CrearEmpleadoSerializer, CustomTokenSerializer


class EsAdmin(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.rol == "admin"


class LoginView(TokenObtainPairView):
    permission_classes = [AllowAny]
    serializer_class = CustomTokenSerializer


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data["refresh"]
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"detail": "Sesión cerrada correctamente."}, status=200)
        except Exception:
            return Response({"error": "Token inválido."}, status=400)


class MiPerfilView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = EmpleadoSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = EmpleadoSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)


class EmpleadoListCreateView(generics.ListCreateAPIView):
    queryset = Empleado.objects.filter(activo=True).select_related("tienda")
    permission_classes = [EsAdmin]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return CrearEmpleadoSerializer
        return EmpleadoSerializer


class EmpleadoDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Empleado.objects.all()
    permission_classes = [EsAdmin]

    def get_serializer_class(self):
        if self.request.method in ["PUT", "PATCH"]:
            return CrearEmpleadoSerializer
        return EmpleadoSerializer

    def destroy(self, request, *args, **kwargs):
        empleado = self.get_object()
        empleado.activo = False
        empleado.save()
        return Response({"detail": "Empleado desactivado."}, status=200)


class CambiarPasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        old_pass = request.data.get("password_actual")
        new_pass = request.data.get("password_nuevo")

        if not user.check_password(old_pass):
            return Response({"error": "Contraseña actual incorrecta."}, status=400)
        if not new_pass or len(new_pass) < 6:
            return Response({"error": "Mínimo 6 caracteres."}, status=400)

        user.set_password(new_pass)
        user.save()
        return Response({"detail": "Contraseña actualizada correctamente."})