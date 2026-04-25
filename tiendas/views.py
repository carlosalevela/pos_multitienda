# tiendas/views.py

from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from core.permissions import EsAdmin, EsAdminOSupervisor, es_superadmin, get_empresa
from .models import Tienda
from .serializers import TiendaSerializer, TiendaSimpleSerializer
from usuarios.models import Empleado
from usuarios.serializers import EmpleadoSerializer

class TiendaListCreateView(generics.ListCreateAPIView):
    serializer_class = TiendaSerializer
    permission_classes = [EsAdmin]

    def get_queryset(self):
        qs = Tienda.objects.prefetch_related("empleados")

        if es_superadmin(self.request):
            empresa_id = self.request.query_params.get("empresa")
            if empresa_id:
                qs = qs.filter(empresa_id=empresa_id)
        else:
            qs = qs.filter(empresa=get_empresa(self.request))

        solo_activas = self.request.query_params.get("activo")
        if solo_activas is not None:
            qs = qs.filter(activo=solo_activas.lower() == "true")

        return qs.order_by("nombre")

    def perform_create(self, serializer):
        from rest_framework.exceptions import ValidationError
        from empresas.models import Empresa

        if es_superadmin(self.request):
            empresa_id = (
                self.request.data.get("empresa")
                or self.request.data.get("empresa_id")
                or self.request.query_params.get("empresa")
            )

            if not empresa_id:
                raise ValidationError({
                    "empresa": "Debes enviar el id de la empresa para crear la sucursal."
                })

            try:
                empresa = Empresa.objects.get(pk=empresa_id)
            except Empresa.DoesNotExist:
                raise ValidationError({
                    "empresa": "La empresa especificada no existe."
                })

            serializer.save(empresa=empresa)
        else:
            serializer.save(empresa=get_empresa(self.request))

class TiendaDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TiendaSerializer
    permission_classes = [EsAdmin]

    def get_queryset(self):
        if es_superadmin(self.request):
            return Tienda.objects.all()
        return Tienda.objects.filter(empresa=get_empresa(self.request))

    def destroy(self, request, *args, **kwargs):
        tienda = self.get_object()
        tienda.activo = False
        tienda.save(update_fields=["activo"])
        return Response(
            {"detail": f"Tienda '{tienda.nombre}' desactivada."},
            status=200,
        )


class TiendaSimpleListView(generics.ListAPIView):
    serializer_class = TiendaSimpleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if es_superadmin(self.request):
            empresa_id = self.request.query_params.get("empresa")
            qs = Tienda.objects.filter(activo=True)
            if empresa_id:
                qs = qs.filter(empresa_id=empresa_id)
            return qs.order_by("nombre")
        return Tienda.objects.filter(
            activo=True,
            empresa=get_empresa(self.request),
        ).order_by("nombre")


class EmpleadosPorTiendaView(APIView):
    permission_classes = [EsAdminOSupervisor]

    def get(self, request, pk):
        try:
            tienda = Tienda.objects.get(pk=pk) if es_superadmin(request) \
                else Tienda.objects.get(pk=pk, empresa=get_empresa(request))
        except Tienda.DoesNotExist:
            return Response({"error": "Tienda no encontrada."}, status=404)

        empleados = Empleado.objects.filter(tienda=tienda, activo=True)
        serializer = EmpleadoSerializer(empleados, many=True)

        return Response({
            "tienda": tienda.nombre,
            "empleados": serializer.data,
            "total": empleados.count(),
        })


class AsignarEmpleadoTiendaView(APIView):
    permission_classes = [EsAdmin]

    def post(self, request, pk):
        try:
            if es_superadmin(request):
                tienda = Tienda.objects.get(pk=pk)
            else:
                tienda = Tienda.objects.get(pk=pk, empresa=get_empresa(request))
        except Tienda.DoesNotExist:
            return Response({"error": "Tienda no encontrada."}, status=404)

        try:
            if es_superadmin(request):
                empleado = Empleado.objects.get(pk=request.data.get("empleado_id"))
            else:
                empleado = Empleado.objects.get(
                    pk=request.data.get("empleado_id"),
                    empresa=get_empresa(request)
                )
        except Empleado.DoesNotExist:
            return Response({"error": "Empleado no encontrado."}, status=404)

        if empleado.empresa_id != tienda.empresa_id:
            return Response(
                {"error": "El empleado y la tienda deben pertenecer a la misma empresa."},
                status=400,
            )

        empleado.tienda = tienda
        empleado.save(update_fields=["tienda"])

        return Response({
            "detail": f"{empleado.nombre} asignado a '{tienda.nombre}' correctamente."
        })