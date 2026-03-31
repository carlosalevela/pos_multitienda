from django.urls import path
from .views import (
    ClienteListCreateView, ClienteDetailView, ClienteSimpleListView,
    SeparadoListCreateView, SeparadoDetailView,
    AbonarSeparadoView, CancelarSeparadoView,
)

urlpatterns = [
    path("",                             ClienteListCreateView.as_view(),  name="clientes"),
    path("simple/",                      ClienteSimpleListView.as_view(),  name="clientes_simple"),
    path("<int:pk>/",                    ClienteDetailView.as_view(),      name="cliente_detail"),
    path("separados/",                   SeparadoListCreateView.as_view(), name="separados"),
    path("separados/<int:pk>/",          SeparadoDetailView.as_view(),     name="separado_detail"),
    path("separados/<int:pk>/abonar/",   AbonarSeparadoView.as_view(),     name="abonar_separado"),
    path("separados/<int:pk>/cancelar/", CancelarSeparadoView.as_view(),   name="cancelar_separado"),
]