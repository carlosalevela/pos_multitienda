from django.urls import path
from .views import (
    CategoriaListCreateView, CategoriaDetailView,
    ProductoListCreateView, ProductoDetailView,
    BuscarProductoPOSView, InventarioListView,
    AjustarInventarioView, MovimientosProductoView,
    TopProductosView,ReactivarProductoView
)

urlpatterns = [
    # Categorías
    path("categorias/",          CategoriaListCreateView.as_view(), name="categorias"),
    path("categorias/<int:pk>/", CategoriaDetailView.as_view(),     name="categoria_detail"),

    # Productos
    path("",                     ProductoListCreateView.as_view(),  name="productos"),
    path("<int:pk>/",            ProductoDetailView.as_view(),      name="producto_detail"),
    path("buscar/",              BuscarProductoPOSView.as_view(),   name="buscar_producto"),

    # Inventario
    path("inventario/",          InventarioListView.as_view(),      name="inventario"),
    path(
        "<int:producto_id>/inventario/<int:tienda_id>/ajustar/",
        AjustarInventarioView.as_view(),
        name="ajustar_inventario"
    ),
    path(
        "<int:producto_id>/inventario/<int:tienda_id>/movimientos/",
        MovimientosProductoView.as_view(),
        name="movimientos_producto"
    ),
    path('top-productos/', TopProductosView.as_view(), name='top-productos'),
    path('<int:pk>/reactivar/',ReactivarProductoView.as_view(),name='reactivar-producto'),
]