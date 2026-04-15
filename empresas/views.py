from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from .models import Empresa
from .serializers import EmpresaSerializer


class EmpresaListCreateView(generics.ListCreateAPIView):
    serializer_class   = EmpresaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Solo admins ven todas; los demás ven solo su empresa
        user = self.request.user
        if user.rol == 'admin' and not hasattr(user, 'empresa') or user.empresa is None:
            return Empresa.objects.all()
        return Empresa.objects.filter(id=user.empresa_id)


class EmpresaDetailView(generics.RetrieveUpdateAPIView):
    serializer_class   = EmpresaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Empresa.objects.filter(id=self.request.user.empresa_id)