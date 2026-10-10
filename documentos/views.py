import base64
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser

from tiendas.models import Tienda
from .models import Documento
from .serializers import DocumentoSerializer, DocumentoUploadSerializer


class DocumentoListView(APIView):
    """Lista documentos según el rol del empleado."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        emp = request.user
        rol = emp.rol

        if rol == 'superadmin':
            qs = Documento.objects.all()
        elif rol in ('admin', 'supervisor'):
            qs = Documento.objects.filter(tienda__empresa=emp.empresa)
        else:
            qs = Documento.objects.filter(tienda=emp.tienda)

        # Filtros opcionales
        tipo      = request.query_params.get('tipo')
        tienda_id = request.query_params.get('tienda_id')
        desde     = request.query_params.get('desde')
        hasta     = request.query_params.get('hasta')

        if tipo:
            qs = qs.filter(tipo=tipo)
        if tienda_id:
            qs = qs.filter(tienda_id=tienda_id)
        if desde:
            qs = qs.filter(fecha__date__gte=desde)
        if hasta:
            qs = qs.filter(fecha__date__lte=hasta)

        qs = qs.select_related('tienda__empresa', 'empleado')[:200]
        return Response(DocumentoSerializer(qs, many=True).data)


class DocumentoUploadView(APIView):
    """Recibe un PDF y lo almacena en la base de datos."""
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser]

    def post(self, request):
        ser = DocumentoUploadSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        data    = ser.validated_data
        archivo = data['archivo']

        try:
            tienda = Tienda.objects.get(id=data['tienda_id'])
        except Tienda.DoesNotExist:
            return Response({'error': 'Tienda no encontrada'}, status=400)

        contenido = archivo.read()
        size_kb   = max(1, round(len(contenido) / 1024))

        doc = Documento.objects.create(
            tienda    = tienda,
            empleado  = request.user,
            tipo      = data['tipo'],
            nombre    = data['nombre'],
            contenido = contenido,
            size_kb   = size_kb,
        )

        return Response(DocumentoSerializer(doc).data, status=status.HTTP_201_CREATED)


class DocumentoDescargarView(APIView):
    """Devuelve el PDF como respuesta descargable."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            doc = Documento.objects.select_related('tienda__empresa').get(pk=pk)
        except Documento.DoesNotExist:
            return Response({'error': 'Documento no encontrado'}, status=404)

        emp = request.user
        # Verificar permiso
        if emp.rol == 'cajero' and doc.tienda != emp.tienda:
            return Response({'error': 'Sin permiso'}, status=403)
        if emp.rol in ('admin', 'supervisor') and doc.tienda.empresa != emp.empresa:
            return Response({'error': 'Sin permiso'}, status=403)

        response = HttpResponse(bytes(doc.contenido), content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{doc.nombre}"'
        return response
