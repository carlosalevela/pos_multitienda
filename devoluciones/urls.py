from django.urls import path
from .views import (
    CrearDevolucionView,
    CancelarDevolucionView,
    DevolucionListView,
    DevolucionDetailView,
)

urlpatterns = [
    # POST  /api/devoluciones/
    path("",                   CrearDevolucionView.as_view(),   name="crear_devolucion"),

    # GET   /api/devoluciones/lista/
    path("lista/",             DevolucionListView.as_view(),    name="lista_devoluciones"),

    # GET   /api/devoluciones/<id>/
    path("<int:pk>/",          DevolucionDetailView.as_view(),  name="devolucion_detail"),

    # POST  /api/devoluciones/<id>/cancelar/
    path("<int:pk>/cancelar/", CancelarDevolucionView.as_view(), name="cancelar_devolucion"),
]