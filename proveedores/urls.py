from django.urls import path
from .views import (
    ProveedorListCreateView, ProveedorDetailView, ProveedorSimpleListView,
    CompraListCreateView, CompraDetailView,
    RecibirCompraView, CancelarCompraView,
)

urlpatterns = [
    path("",                           ProveedorListCreateView.as_view(), name="proveedores"),
    path("simple/",                    ProveedorSimpleListView.as_view(), name="proveedores_simple"),
    path("<int:pk>/",                  ProveedorDetailView.as_view(),     name="proveedor_detail"),
    path("compras/",                   CompraListCreateView.as_view(),    name="compras"),
    path("compras/<int:pk>/",          CompraDetailView.as_view(),        name="compra_detail"),
    path("compras/<int:pk>/recibir/",  RecibirCompraView.as_view(),       name="recibir_compra"),
    path("compras/<int:pk>/cancelar/", CancelarCompraView.as_view(),      name="cancelar_compra"),
]