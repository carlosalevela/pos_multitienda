from django.urls import path
from .views import (
    CrearVentaView, VentaListView, VentaDetailView,
    AnularVentaView, VentaDisponibleDevolucionView,
    CambioPOSView, DashboardAdminView,
)

urlpatterns = [
    path("",                               CrearVentaView.as_view(),                name="crear_venta"),
    path("lista/",                         VentaListView.as_view(),                 name="lista_ventas"),
    path("dashboard/",                     DashboardAdminView.as_view(),            name="dashboard_admin"),
    path("<int:pk>/",                      VentaDetailView.as_view(),               name="venta_detail"),
    path("<int:pk>/anular/",               AnularVentaView.as_view(),               name="anular_venta"),
    path("<int:pk>/disponible-devolucion/", VentaDisponibleDevolucionView.as_view(), name="venta_disponible_dev"),
    path("cambio-pos/",                    CambioPOSView.as_view(),                 name="cambio_pos"),
]