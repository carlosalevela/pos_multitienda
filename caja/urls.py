from django.urls import path
from .views import (
    AbrirCajaView, CerrarCajaView,
    SesionActivaView, SesionCajaListView,
    SesionCajaDetailView, ResumenCierreView,  # ← agregar
)

urlpatterns = [
    path("abrir/",                      AbrirCajaView.as_view(),        name="abrir_caja"),
    path("<int:pk>/cerrar/",            CerrarCajaView.as_view(),       name="cerrar_caja"),
    path("<int:pk>/resumen-cierre/",    ResumenCierreView.as_view(),    name="resumen_cierre"),  # ← nueva
    path("activa/<int:tienda_id>/",     SesionActivaView.as_view(),     name="sesion_activa"),
    path("historial/",                  SesionCajaListView.as_view(),   name="historial_caja"),
    path("historial/<int:pk>/",         SesionCajaDetailView.as_view(), name="sesion_detail"),
]