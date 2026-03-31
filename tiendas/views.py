from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import Tienda
from .serializers import TiendaSerializer, TiendaSimpleSerializer
from usuarios.models import Empleado
from usuarios.serializers import EmpleadoSerializer


class EsAdmin(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.rol == "admin"

class EsAdminOSupervisor(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.rol in ["admin", "supervisor"]


class TiendaListCreateView(generics.ListCreateAPIView):
    serializer_class   = TiendaSerializer
    permission_classes = [EsAdmin]

    def get_queryset(self):
        qs = Tienda.objects.prefetch_related("empleados")
        solo_activas = self.request.query_params.get("activo")
        if solo_activas is not None:
            qs = qs.filter(activo=solo_activas.lower() == "true")
        return qs


class TiendaDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset           = Tienda.objects.all()
    serializer_class   = TiendaSerializer
    permission_classes = [EsAdmin]

    def destroy(self, request, *args, **kwargs):
        tienda = self.get_object()
        tienda.activo = False
        tienda.save()
        return Response({"detail": f"Tienda '{tienda.nombre}' desactivada."}, status=200)


class TiendaSimpleListView(generics.ListAPIView):
    queryset           = Tienda.objects.filter(activo=True).order_by("nombre")
    serializer_class   = TiendaSimpleSerializer
    permission_classes = [IsAuthenticated]


class EmpleadosPorTiendaView(APIView):
    permission_classes = [EsAdminOSupervisor]

    def get(self, request, pk):
        try:
            tienda = Tienda.objects.get(pk=pk)
        except Tienda.DoesNotExist:
            return Response({"error": "Tienda no encontrada."}, status=404)

        empleados  = Empleado.objects.filter(tienda=tienda, activo=True)
        serializer = EmpleadoSerializer(empleados, many=True)
        return Response({
            "tienda":    tienda.nombre,
            "empleados": serializer.data,
            "total":     empleados.count()
        })


class AsignarEmpleadoTiendaView(APIView):
    permission_classes = [EsAdmin]

    def post(self, request, pk):
        try:
            tienda   = Tienda.objects.get(pk=pk)
            empleado = Empleado.objects.get(pk=request.data.get("empleado_id"))
        except Tienda.DoesNotExist:
            return Response({"error": "Tienda no encontrada."}, status=404)
        except Empleado.DoesNotExist:
            return Response({"error": "Empleado no encontrado."}, status=404)

        empleado.tienda = tienda
        empleado.save()
        return Response({
            "detail": f"{empleado.nombre} asignado a '{tienda.nombre}' correctamente."
        })