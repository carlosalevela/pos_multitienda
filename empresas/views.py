from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied

from core.permissions import EsAdmin, es_superadmin, get_empresa
from .models import Empresa
from .serializers import EmpresaSerializer, EmpresaConfigMayoreoSerializer


class EmpresaListCreateView(generics.ListCreateAPIView):
    serializer_class   = EmpresaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if es_superadmin(self.request):
            return Empresa.objects.all().order_by("nombre")
        user = self.request.user
        if hasattr(user, "empresa") and user.empresa_id:
            return Empresa.objects.filter(id=user.empresa_id)
        return Empresa.objects.none()

    def perform_create(self, serializer):
        if not es_superadmin(self.request):
            raise PermissionDenied(
                "Solo el superadmin puede crear empresas.")
        serializer.save()


class EmpresaDetailView(generics.RetrieveUpdateAPIView):
    serializer_class   = EmpresaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if es_superadmin(self.request):
            return Empresa.objects.all()
        user = self.request.user
        if hasattr(user, "empresa") and user.empresa_id:
            return Empresa.objects.filter(id=user.empresa_id)
        return Empresa.objects.none()

    def update(self, request, *args, **kwargs):
        if not es_superadmin(request):
            campos_bloqueados = ["nit"]
            for campo in campos_bloqueados:
                if campo in request.data:
                    raise PermissionDenied(
                        f"No tienes permiso para modificar '{campo}'.")
        return super().update(request, *args, **kwargs)


class EmpresaConfigMayoreoView(APIView):
    """
    GET  /api/empresas/<id>/mayoreo/  → leer config actual
    PATCH /api/empresas/<id>/mayoreo/ → actualizar config
    
    Solo el admin de la empresa o superadmin puede modificarlo.
    """
    permission_classes = [IsAuthenticated]

    def _get_empresa(self, request, pk):
        """Resuelve la empresa validando permisos."""
        if es_superadmin(request):
            try:
                return Empresa.objects.get(pk=pk)
            except Empresa.DoesNotExist:
                return None
        # Admin normal: solo puede ver/editar su propia empresa
        empresa = get_empresa(request)
        if empresa and empresa.pk == int(pk):
            return empresa
        return None

    def get(self, request, pk):
        empresa = self._get_empresa(request, pk)
        if not empresa:
            raise PermissionDenied(
                "No tienes acceso a esta empresa.")
        serializer = EmpresaConfigMayoreoSerializer(empresa)
        return Response(serializer.data)

    def patch(self, request, pk):
        # Solo admin o superadmin puede modificar
        if not (es_superadmin(request) or
                request.user.rol == 'admin'):
            raise PermissionDenied(
                "Solo el administrador puede modificar "
                "la configuración de mayoreo.")

        empresa = self._get_empresa(request, pk)
        if not empresa:
            raise PermissionDenied(
                "No tienes acceso a esta empresa.")

        serializer = EmpresaConfigMayoreoSerializer(
            empresa,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({
            "detail": "Configuración de mayoreo actualizada.",
            **serializer.data,
        })