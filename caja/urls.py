from django.urls import path
from .views import (
    AbrirCajaView, CerrarCajaView,
    SesionActivaView, SesionCajaListView,
    SesionCajaDetailView, ResumenCierreView,
    SesionGastosView, DashboardCajaView,
)

urlpatterns = [
    path("abrir/",                      AbrirCajaView.as_view(),        name="abrir_caja"),
    path("<int:pk>/cerrar/",            CerrarCajaView.as_view(),       name="cerrar_caja"),
    path("<int:pk>/resumen-cierre/",    ResumenCierreView.as_view(),    name="resumen_cierre"),
    path("<int:pk>/gastos/",            SesionGastosView.as_view(),     name="sesion_gastos"),
    path("activa/<int:tienda_id>/",     SesionActivaView.as_view(),     name="sesion_activa"),
    path("dashboard/",                  DashboardCajaView.as_view(),    name="dashboard_caja"),
    path("historial/",                  SesionCajaListView.as_view(),   name="historial_caja"),
    path("historial/<int:pk>/",         SesionCajaDetailView.as_view(), name="sesion_detail"),
]