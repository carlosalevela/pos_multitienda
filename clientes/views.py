from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.db.models import Q
from decimal import Decimal

from .models import Cliente, Separado, AbonoSeparado
from .serializers import (
    ClienteSerializer, ClienteSimpleSerializer,
    SeparadoSerializer,
)


class EsAdminOSupervisor(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.rol in ["admin", "supervisor"]


# ── Clientes ──────────────────────────────────────────────────
class ClienteListCreateView(generics.ListCreateAPIView):
    serializer_class   = ClienteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Cliente.objects.filter(activo=True).order_by("nombre")
        q  = self.request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(nombre__icontains=q)     |
                Q(apellido__icontains=q)   |
                Q(cedula_nit__icontains=q) |
                Q(telefono__icontains=q)
            )
        return qs

class ClienteDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset           = Cliente.objects.all()
    serializer_class   = ClienteSerializer
    permission_classes = [IsAuthenticated]

    def destroy(self, request, *args, **kwargs):
        cliente = self.get_object()
        cliente.activo = False
        cliente.save()
        return Response({"detail": f"Cliente '{cliente.nombre}' desactivado."})

class ClienteSimpleListView(generics.ListAPIView):
    serializer_class   = ClienteSimpleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Cliente.objects.filter(activo=True).order_by("nombre")
        q  = self.request.query_params.get("q")
        if q:
            qs = qs.filter(Q(nombre__icontains=q) | Q(cedula_nit__icontains=q))
        return qs


# ── Separados ─────────────────────────────────────────────────
class SeparadoListCreateView(generics.ListCreateAPIView):
    serializer_class   = SeparadoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs        = Separado.objects.select_related("cliente","tienda","empleado").prefetch_related("detalles","abonos")
        tienda_id = self.request.query_params.get("tienda_id")
        estado    = self.request.query_params.get("estado")
        cliente   = self.request.query_params.get("cliente_id")
        if tienda_id: qs = qs.filter(tienda_id=tienda_id)
        if estado:    qs = qs.filter(estado=estado)
        if cliente:   qs = qs.filter(cliente_id=cliente)
        return qs.order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(empleado=self.request.user)

class SeparadoDetailView(generics.RetrieveAPIView):
    queryset           = Separado.objects.prefetch_related("detalles__producto","abonos__empleado")
    serializer_class   = SeparadoSerializer
    permission_classes = [IsAuthenticated]

class AbonarSeparadoView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        try:
            separado = Separado.objects.select_for_update().get(pk=pk)
        except Separado.DoesNotExist:
            return Response({"error": "Separado no encontrado."}, status=404)

        if separado.estado != "activo":
            return Response({"error": f"Este separado está {separado.estado}."}, status=400)

        monto = request.data.get("monto")
        if not monto or float(monto) <= 0:
            return Response({"error": "El monto debe ser mayor a 0."}, status=400)

        monto = Decimal(monto)
        if monto >  Decimal(separado.saldo_pendiente):
            return Response({"error": f"Excede el saldo pendiente de ${separado.saldo_pendiente}."}, status=400)

        AbonoSeparado.objects.create(
            separado    = separado,
            empleado    = request.user,
            monto       = monto,
            metodo_pago = request.data.get("metodo_pago", "efectivo"),
        )

        separado.abono_acumulado += monto
        separado.saldo_pendiente -= monto

        if separado.saldo_pendiente <= 0:
            separado.estado          = "pagado"
            separado.saldo_pendiente = 0

        separado.save()

        return Response({
            "detail":          "Abono registrado correctamente.",
            "abono":           monto,
            "abono_acumulado": float(separado.abono_acumulado),
            "saldo_pendiente": float(separado.saldo_pendiente),
            "estado":          separado.estado,
        })

class CancelarSeparadoView(APIView):
    permission_classes = [EsAdminOSupervisor]

    def post(self, request, pk):
        try:
            separado = Separado.objects.get(pk=pk)
        except Separado.DoesNotExist:
            return Response({"error": "Separado no encontrado."}, status=404)

        if separado.estado == "pagado":
            return Response({"error": "No se puede cancelar un separado ya pagado."}, status=400)

        separado.estado = "cancelado"
        separado.save()
        return Response({"detail": f"Separado #{separado.id} cancelado."})