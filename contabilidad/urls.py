from django.urls import path
from .views import (
    GastoListCreateView, GastoDetailView,
    ResumenDiarioView, ResumenMensualView,
    ResumenAnualView, GastosResumenRangoView,
    ProductosMasVendidosView, EstadoResultadosView,
    ComparativoTiendasView, VentasPorEmpleadoView,
    PuntoEquilibrioView, FlujoCajaView,
    ExportarContabilidadView,
)

urlpatterns = [
    path("gastos/",                       GastoListCreateView.as_view(),      name="gastos"),
    path("gastos/<int:pk>/",              GastoDetailView.as_view(),          name="gasto_detail"),
    path("gastos/resumen-rango/",         GastosResumenRangoView.as_view(),   name="gastos_resumen_rango"),
    path("reportes/diario/",              ResumenDiarioView.as_view(),        name="reporte_diario"),
    path("reportes/mensual/",             ResumenMensualView.as_view(),       name="reporte_mensual"),
    path("reportes/anual/",               ResumenAnualView.as_view(),         name="resumen_anual"),
    path("reportes/top-productos/",       ProductosMasVendidosView.as_view(), name="top_productos"),
    path("reportes/estado-resultados/",   EstadoResultadosView.as_view(),     name="estado_resultados"),
    path("reportes/comparativo-tiendas/", ComparativoTiendasView.as_view(),   name="comparativo_tiendas"),
    path("reportes/ventas-por-empleado/", VentasPorEmpleadoView.as_view(),    name="ventas_por_empleado"),
    path("reportes/punto-equilibrio/",    PuntoEquilibrioView.as_view(),      name="punto_equilibrio"),
    path("reportes/flujo-caja/",          FlujoCajaView.as_view(),            name="flujo_caja"),
    path("reportes/exportar/",            ExportarContabilidadView.as_view(), name="exportar_contabilidad"),
]
