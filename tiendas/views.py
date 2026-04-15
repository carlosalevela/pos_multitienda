from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import Tienda
from .serializers import TiendaSerializer, TiendaSimpleSerializer
from usuarios.models import Empleado
from usuarios.serializers import EmpleadoSerializer


# ── Permisos ───────────────────────────────────────────────────

class EsAdmin(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.rol == "admin"


class EsAdminOSupervisor(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.rol in ["admin", "supervisor"]


# ── Helper empresa ─────────────────────────────────────────────

def _get_empresa(request):
    return request.user.empresa


# ── Tiendas ────────────────────────────────────────────────────

class TiendaListCreateView(generics.ListCreateAPIView):
    serializer_class   = TiendaSerializer
    permission_classes = [EsAdmin]

    def get_queryset(self):
        empresa = _get_empresa(self.request)
        qs = Tienda.objects.prefetch_related("empleados").filter(
            empresa=empresa,        # ✅
        )
        solo_activas = self.request.query_params.get("activo")
        if solo_activas is not None:
            qs = qs.filter(activo=solo_activas.lower() == "true")
        return qs

    def perform_create(self, serializer):
        serializer.save(empresa=_get_empresa(self.request))  # ✅


class TiendaDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class   = TiendaSerializer
    permission_classes = [EsAdmin]

    def get_queryset(self):
        # ✅ scoped — no puede editar tiendas de otras empresas
        return Tienda.objects.filter(empresa=_get_empresa(self.request))

    def destroy(self, request, *args, **kwargs):
        tienda = self.get_object()
        tienda.activo = False
        tienda.save()
        return Response(
            {"detail": f"Tienda '{tienda.nombre}' desactivada."},
            status=200)


class TiendaSimpleListView(generics.ListAPIView):
    serializer_class   = TiendaSimpleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # ✅ dropdown solo muestra tiendas de la empresa del usuario
        return Tienda.objects.filter(
            activo=True,
            empresa=_get_empresa(self.request),
        ).order_by("nombre")


# ── Empleados por tienda ───────────────────────────────────────

class EmpleadosPorTiendaView(APIView):
    permission_classes = [EsAdminOSupervisor]

    def get(self, request, pk):
        empresa = _get_empresa(request)
        try:
            # ✅ scoped — no puede ver empleados de tiendas ajenas
            tienda = Tienda.objects.get(pk=pk, empresa=empresa)
        except Tienda.DoesNotExist:
            return Response({"error": "Tienda no encontrada."}, status=404)

        empleados  = Empleado.objects.filter(tienda=tienda, activo=True)
        serializer = EmpleadoSerializer(empleados, many=True)
        return Response({
            "tienda":    tienda.nombre,
            "empleados": serializer.data,
            "total":     empleados.count(),
        })


# ── Asignar empleado a tienda ──────────────────────────────────

class AsignarEmpleadoTiendaView(APIView):
    permission_classes = [EsAdmin]

    def post(self, request, pk):
        empresa = _get_empresa(request)
        try:
            # ✅ verifica que tienda Y empleado sean de la misma empresa
            tienda = Tienda.objects.get(pk=pk, empresa=empresa)
        except Tienda.DoesNotExist:
            return Response({"error": "Tienda no encontrada."}, status=404)

        try:
            empleado = Empleado.objects.get(
                pk=request.data.get("empleado_id"),
                empresa=empresa,    # ✅ no puede asignar empleados de otra empresa
            )
        except Empleado.DoesNotExist:
            return Response({"error": "Empleado no encontrado."}, status=404)

        empleado.tienda = tienda
        empleado.save()
        return Response({
            "detail": f"{empleado.nombre} asignado a '{tienda.nombre}' correctamente."
        })