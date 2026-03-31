from django.urls import path
from .views import CrearDevolucionView, DevolucionListView, DevolucionDetailView

urlpatterns = [
    path("",          CrearDevolucionView.as_view(), name="crear_devolucion"),
    path("lista/",    DevolucionListView.as_view(),  name="lista_devoluciones"),
    path("<int:pk>/", DevolucionDetailView.as_view(),name="devolucion_detail"),
]