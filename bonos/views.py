from decimal import Decimal

from django.db import transaction
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Bono, UsoBono
from .serializers import (
    BonoListSerializer,
    BonoSerializer,
    RedimirBonoSerializer,
    ValidarBonoSerializer,
)


class BonoVenderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        empresa_id = request.data.get('empresa_id')
        tienda_id  = request.data.get('tienda_id')
        valor      = request.data.get('valor')
        venta_id   = request.data.get('venta_id')
        cliente_id = request.data.get('cliente_id')

        if not empresa_id or not tienda_id or not valor:
            return Response(
                {'error': 'empresa_id, tienda_id y valor son requeridos'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            valor_dec = Decimal(str(valor))
            if valor_dec <= 0:
                raise ValueError
        except (ValueError, Exception):
            return Response(
                {'error': 'valor debe ser un número positivo'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bono = Bono.objects.create(
            empresa_id    = empresa_id,
            tienda_origen_id = tienda_id,
            valor_original = valor_dec,
            saldo          = valor_dec,
            venta_origen_id = venta_id or None,
            cliente_id     = cliente_id or None,
        )
        return Response(BonoSerializer(bono).data, status=status.HTTP_201_CREATED)


class BonoValidarView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = ValidarBonoSerializer(data=request.query_params)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        codigo = serializer.validated_data['codigo'].strip().upper()
        try:
            bono = Bono.objects.get(codigo=codigo)
        except Bono.DoesNotExist:
            return Response(
                {'error': 'Código de bono no encontrado'},
                status=status.HTTP_404_NOT_FOUND,
            )

        data = BonoSerializer(bono).data
        data['esta_vigente'] = bono.esta_vigente
        return Response(data)


class BonoRedimirView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = RedimirBonoSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        codigo   = serializer.validated_data['codigo'].strip().upper()
        monto    = serializer.validated_data['monto']
        venta_id = serializer.validated_data['venta_id']
        tienda_id = serializer.validated_data['tienda_id']

        try:
            bono = Bono.objects.select_for_update().get(codigo=codigo)
        except Bono.DoesNotExist:
            return Response(
                {'error': 'Código de bono no encontrado'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not bono.esta_vigente:
            return Response(
                {'error': f'El bono no está vigente (estado: {bono.estado})'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if monto <= 0:
            return Response(
                {'error': 'El monto a redimir debe ser positivo'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        monto_a_usar = min(monto, bono.saldo)
        saldo_antes   = bono.saldo
        saldo_despues = bono.saldo - monto_a_usar

        UsoBono.objects.create(
            bono          = bono,
            venta_id      = venta_id,
            tienda_id     = tienda_id,
            monto_usado   = monto_a_usar,
            saldo_antes   = saldo_antes,
            saldo_despues = saldo_despues,
        )

        bono.saldo = saldo_despues
        if bono.saldo == 0:
            bono.estado = 'redimido'
        bono.save(update_fields=['saldo', 'estado'])

        return Response({
            'codigo':        bono.codigo,
            'monto_usado':   str(monto_a_usar),
            'saldo_antes':   str(saldo_antes),
            'saldo_despues': str(saldo_despues),
            'estado':        bono.estado,
        })


class BonoListView(generics.ListAPIView):
    serializer_class   = BonoListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs         = Bono.objects.select_related('tienda_origen')
        empresa_id = self.request.query_params.get('empresa_id')
        tienda_id  = self.request.query_params.get('tienda_id')
        estado     = self.request.query_params.get('estado')

        if empresa_id:
            qs = qs.filter(empresa_id=empresa_id)
        if tienda_id:
            qs = qs.filter(tienda_origen_id=tienda_id)
        if estado:
            qs = qs.filter(estado=estado)
        return qs


class BonoDetailView(generics.RetrieveAPIView):
    serializer_class   = BonoSerializer
    permission_classes = [IsAuthenticated]
    lookup_field       = 'codigo'

    def get_queryset(self):
        return Bono.objects.prefetch_related('usos__tienda')
