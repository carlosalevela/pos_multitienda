from django.urls import path
from .views import (
    TiendaListCreateView, TiendaDetailView,
    TiendaSimpleListView, EmpleadosPorTiendaView,
    AsignarEmpleadoTiendaView,
)

urlpatterns = [
    path("",                           TiendaListCreateView.as_view(),      name="tiendas"),
    path("simple/",                    TiendaSimpleListView.as_view(),      name="tiendas_simple"),
    path("<int:pk>/",                  TiendaDetailView.as_view(),          name="tienda_detail"),
    path("<int:pk>/empleados/",        EmpleadosPorTiendaView.as_view(),    name="empleados_tienda"),
    path("<int:pk>/asignar-empleado/", AsignarEmpleadoTiendaView.as_view(), name="asignar_empleado"),
]