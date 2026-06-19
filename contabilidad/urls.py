from django.urls import path
from .views import (
    GastoListCreateView, GastoDetailView,
    ResumenDiarioView, ResumenMensualView,
    ResumenAnualView, GastosResumenRangoView,
    ProductosMasVendidosView,
)

urlpatterns = [
    path("gastos/",                   GastoListCreateView.as_view(),     name="gastos"),
    path("gastos/<int:pk>/",          GastoDetailView.as_view(),         name="gasto_detail"),
    path("gastos/resumen-rango/",     GastosResumenRangoView.as_view(),  name="gastos_resumen_rango"),
    path("reportes/diario/",          ResumenDiarioView.as_view(),       name="reporte_diario"),
    path("reportes/mensual/",         ResumenMensualView.as_view(),      name="reporte_mensual"),
    path("reportes/anual/",           ResumenAnualView.as_view(),        name="resumen_anual"),
    path("reportes/top-productos/",   ProductosMasVendidosView.as_view(), name="top_productos"),
]
