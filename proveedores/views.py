from django.db import transaction
from django.utils import timezone
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import EsAdmin, EsAdminOSupervisor, es_superadmin, get_empresa, scope_qs
from .models import Proveedor, Compra
from .serializers import ProveedorSerializer, ProveedorSimpleSerializer, CompraSerializer
from productos.models import Inventario, MovimientoInventario, Producto, generar_codigo_barras_interno
from contabilidad.models import Gasto


# ── Proveedores ───────────────────────────────────────────────

class ProveedorListCreateView(generics.ListCreateAPIView):
    serializer_class   = ProveedorSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        qs = scope_qs(
            self.request,
            Proveedor.objects.filter(activo=True),
            campo_empresa="empresa",
        )
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(nombre__icontains=q)
        return qs.order_by("nombre")

    def perform_create(self, serializer):
        if es_superadmin(self.request):
            empresa_id = self.request.data.get("empresa_id")
            if not empresa_id:
                raise PermissionDenied(
                    "El superadmin debe especificar una empresa.")
            serializer.save(empresa_id=empresa_id)
        else:
            serializer.save(empresa=get_empresa(self.request))


class ProveedorDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class   = ProveedorSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        if es_superadmin(self.request):
            return Proveedor.objects.all()
        return Proveedor.objects.filter(
            empresa=get_empresa(self.request))

    def perform_update(self, serializer):
        if es_superadmin(self.request):
            empresa_id = self.request.data.get("empresa_id")
            if empresa_id:
                serializer.save(empresa_id=empresa_id)
            else:
                serializer.save()
        else:
            serializer.save(empresa=get_empresa(self.request))

    def destroy(self, request, *args, **kwargs):
        proveedor = self.get_object()
        proveedor.activo = False
        proveedor.save()
        return Response(
            {"detail": f"Proveedor '{proveedor.nombre}' desactivado."})


class ProveedorSimpleListView(generics.ListAPIView):
    serializer_class   = ProveedorSimpleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Proveedor.objects.filter(activo=True)

        if es_superadmin(self.request):
            empresa_id = self.request.query_params.get("empresa")
            tienda_id  = self.request.query_params.get("tienda_id")
            if empresa_id:
                qs = qs.filter(empresa_id=empresa_id)
            elif tienda_id:
                qs = qs.filter(empresa__tienda__id=tienda_id)
        else:
            qs = qs.filter(empresa=get_empresa(self.request))

        return qs.order_by("nombre")


# ── Compras ───────────────────────────────────────────────────

class CompraListCreateView(generics.ListCreateAPIView):
    serializer_class   = CompraSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        qs = scope_qs(
            self.request,
            Compra.objects.select_related(
                "proveedor", "tienda", "empleado"
            ).prefetch_related("detalles"),
        )

        tienda_id = self.request.query_params.get("tienda_id")
        estado    = self.request.query_params.get("estado")
        if tienda_id: qs = qs.filter(tienda_id=tienda_id)
        if estado:    qs = qs.filter(estado=estado)
        return qs.order_by("-fecha_orden")

    def perform_create(self, serializer):
        if es_superadmin(self.request):
            total_compras = Compra.objects.count()
        else:
            empresa       = get_empresa(self.request)
            total_compras = Compra.objects.filter(
                tienda__empresa=empresa).count()

        numero = f"OC-{(total_compras + 1):05d}"
        serializer.save(
            empleado=self.request.user,
            numero_orden=numero,
        )


class CompraDetailView(generics.RetrieveAPIView):
    serializer_class   = CompraSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        if es_superadmin(self.request):
            return Compra.objects.prefetch_related("detalles__producto")
        return Compra.objects.filter(
            tienda__empresa=get_empresa(self.request)
        ).prefetch_related("detalles__producto")


class RecibirCompraView(APIView):
    permission_classes = [EsAdminOSupervisor]

    @transaction.atomic
    def post(self, request, pk):
        try:
            qs     = Compra.objects.prefetch_related(
                "detalles__producto", "detalles__categoria")
            compra = qs.get(pk=pk) if es_superadmin(request) \
                else qs.get(pk=pk,
                            tienda__empresa=get_empresa(request))
        except Compra.DoesNotExist:
            return Response(
                {"error": "Compra no encontrada."}, status=404)

        if compra.estado == "recibida":
            return Response(
                {"error": "Esta compra ya fue recibida."}, status=400)
        if compra.estado == "cancelada":
            return Response(
                {"error": "No se puede recibir una compra cancelada."},
                status=400)

        # precios:        {str(detalleId): precioVenta}
        # precios_mayoreo:{str(detalleId): precioMayoreo}
        precios_venta   = request.data.get('precios', {})
        precios_mayoreo = request.data.get('precios_mayoreo', {})

        empresa                = compra.tienda.empresa
        productos_actualizados = []

        for detalle in compra.detalles.all():
            # Crear producto nuevo si es modo libre
            if not detalle.producto:
                nuevo_producto = Producto.objects.create(
                    nombre        = detalle.nombre_libre or "Producto sin nombre",
                    categoria     = detalle.categoria,
                    precio_compra = detalle.precio_unitario,
                    precio_venta  = detalle.precio_unitario,
                    codigo_barras = generar_codigo_barras_interno(),
                    empresa       = empresa,
                    activo        = True,
                )
                detalle.producto = nuevo_producto
                detalle.save()

            producto        = detalle.producto
            detalle_id_str  = str(detalle.id)
            precio_venta_nuevo  = precios_venta.get(detalle_id_str)
            precio_mayoreo_nuevo = precios_mayoreo.get(detalle_id_str)

            campos_a_actualizar = ['precio_compra']
            producto.precio_compra = detalle.precio_unitario  # siempre actualiza costo

            if precio_venta_nuevo is not None:
                try:
                    producto.precio_venta = float(precio_venta_nuevo)
                    campos_a_actualizar.append('precio_venta')
                except (ValueError, TypeError):
                    pass

            if precio_mayoreo_nuevo is not None:
                try:
                    producto.precio_mayoreo = float(precio_mayoreo_nuevo)
                    campos_a_actualizar.append('precio_mayoreo')
                except (ValueError, TypeError):
                    pass

            producto.save(update_fields=campos_a_actualizar)

            # Actualizar inventario
            inv, _ = Inventario.objects.select_for_update().get_or_create(
                producto = detalle.producto,
                tienda   = compra.tienda,
                defaults = {
                    "stock_actual": 0,
                    "stock_minimo": 0,
                    "stock_maximo": 0,
                }
            )
            inv.stock_actual += detalle.cantidad
            inv.save()

            # Registrar movimiento
            MovimientoInventario.objects.create(
                producto        = detalle.producto,
                tienda          = compra.tienda,
                empleado        = request.user,
                tipo            = "entrada",
                cantidad        = detalle.cantidad,
                referencia_tipo = "compra",
                referencia_id   = compra.id,
                observacion     = f"Recepción orden {compra.numero_orden}",
            )

            productos_actualizados.append({
                "producto":          producto.nombre,
                "es_nuevo":          detalle.nombre_libre != "",
                "codigo_barras":     producto.codigo_barras,
                "categoria":         detalle.categoria.nombre
                                     if detalle.categoria else None,
                "cantidad_recibida": float(detalle.cantidad),
                "stock_actual":      float(inv.stock_actual),
                "precio_venta":  float(producto.precio_venta),
                "precio_compra": float(producto.precio_compra),
            })

        compra.estado          = "recibida"
        compra.fecha_recepcion = timezone.now()
        compra.save()

        # Registrar gasto contable
        if compra.total > 0:
            Gasto.objects.create(
                tienda      = compra.tienda,
                empleado    = request.user,
                categoria   = 'proveedor',
                descripcion = (f'Recepción {compra.numero_orden} — '
                               f'{compra.proveedor.nombre}'),
                monto       = compra.total,
                metodo_pago = 'transferencia',
                visibilidad = 'solo_admin',
            )

        return Response({
            "detail":    f"Compra {compra.numero_orden} recibida correctamente.",
            "tienda":    compra.tienda.nombre,
            "productos": productos_actualizados,
        })


class CancelarCompraView(APIView):
    permission_classes = [EsAdmin]

    def post(self, request, pk):
        try:
            compra = Compra.objects.get(pk=pk) \
                if es_superadmin(request) \
                else Compra.objects.get(
                    pk=pk,
                    tienda__empresa=get_empresa(request))
        except Compra.DoesNotExist:
            return Response(
                {"error": "Compra no encontrada."}, status=404)

        if compra.estado == "recibida":
            return Response(
                {"error": "No se puede cancelar una compra ya recibida."},
                status=400)

        compra.estado = "cancelada"
        compra.save()
        return Response(
            {"detail": f"Compra {compra.numero_orden} cancelada."})
