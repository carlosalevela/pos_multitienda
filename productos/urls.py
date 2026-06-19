from django.urls import path
from .views import (
    CategoriaListCreateView, CategoriaDetailView,
    ProductoListCreateView, ProductoDetailView,
    BuscarProductoPOSView, InventarioListView,
    AjustarInventarioView, MovimientosProductoView,
    TopProductosView, ReactivarProductoView, ImportarProductosView,
    DashboardInventarioView, MovimientosRecientesView,
    ExportarInventarioView, AveriasView, RecuperarAveriaView,
)

urlpatterns = [
    # Categorías
    path("categorias/",          CategoriaListCreateView.as_view(), name="categorias"),
    path("categorias/<int:pk>/", CategoriaDetailView.as_view(),     name="categoria_detail"),

    # Productos
    path("",                     ProductoListCreateView.as_view(),  name="productos"),
    path("importar/",            ImportarProductosView.as_view(),   name="importar_productos"),
    path("buscar/",              BuscarProductoPOSView.as_view(),   name="buscar_producto"),
    path("<int:pk>/",            ProductoDetailView.as_view(),      name="producto_detail"),
    path("<int:pk>/reactivar/",  ReactivarProductoView.as_view(),   name="reactivar-producto"),

    # Inventario
    path("inventario/",            InventarioListView.as_view(),       name="inventario"),
    path("inventario/exportar/",   ExportarInventarioView.as_view(),   name="exportar_inventario"),
    path(
        "<int:producto_id>/inventario/<int:tienda_id>/ajustar/",
        AjustarInventarioView.as_view(),
        name="ajustar_inventario",
    ),
    path(
        "<int:producto_id>/inventario/<int:tienda_id>/movimientos/",
        MovimientosProductoView.as_view(),
        name="movimientos_producto",
    ),

    # Movimientos recientes (feed global)
    path("movimientos/recientes/", MovimientosRecientesView.as_view(), name="movimientos_recientes"),

    # Averías
    path("averias/", AveriasView.as_view(), name="averias"),
    path(
        "<int:producto_id>/inventario/<int:tienda_id>/recuperar-averia/",
        RecuperarAveriaView.as_view(),
        name="recuperar_averia",
    ),

    # Analytics / Dashboard
    path("top-productos/",  TopProductosView.as_view(),        name="top-productos"),
    path("dashboard/",      DashboardInventarioView.as_view(), name="dashboard_inventario"),
]