from django.urls import path
from .views import CrearVentaView, VentaListView, VentaDetailView, AnularVentaView,VentaDisponibleDevolucionView

urlpatterns = [
    path("",                 CrearVentaView.as_view(),  name="crear_venta"),
    path("lista/",           VentaListView.as_view(),   name="lista_ventas"),
    path("<int:pk>/",        VentaDetailView.as_view(), name="venta_detail"),
    path("<int:pk>/anular/", AnularVentaView.as_view(), name="anular_venta"),
    path('<int:pk>/disponible-devolucion/', VentaDisponibleDevolucionView.as_view()),
]