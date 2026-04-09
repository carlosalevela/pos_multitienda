from django.urls import path
from .views import (
    GastoListCreateView, GastoDetailView,
    ResumenDiarioView, ResumenMensualView, ProductosMasVendidosView,ResumenAnualView
)

urlpatterns = [
    path("gastos/",               GastoListCreateView.as_view(),     name="gastos"),
    path("gastos/<int:pk>/",      GastoDetailView.as_view(),         name="gasto_detail"),
    path("reportes/diario/",      ResumenDiarioView.as_view(),       name="reporte_diario"),
    path("reportes/mensual/",     ResumenMensualView.as_view(),      name="reporte_mensual"),
    path("reportes/top-productos/", ProductosMasVendidosView.as_view(), name="top_productos"),
    path("reportes/anual/", ResumenAnualView.as_view(), name="resumen-anual"),
]