# empresas/views.py

from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied

from core.permissions import EsAdmin, es_superadmin, get_empresa
from .models import Empresa
from .serializers import EmpresaSerializer


class EmpresaListCreateView(generics.ListCreateAPIView):
    serializer_class = EmpresaSerializer
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
    serializer_class = EmpresaSerializer
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