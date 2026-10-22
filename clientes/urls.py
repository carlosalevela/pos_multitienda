from django.urls import path
from .views import (
    ClienteListCreateView, ClienteDetailView, ClienteSimpleListView,
    ClienteResumenView, CreditosClienteView,
    SeparadoListCreateView, SeparadoDetailView,
    AbonarSeparadoView, CancelarSeparadoView, CambiarProductoSeparadoView,
    AlertasSeparadosView, AbonosPorFechaView, RecordatoriosSeparadosView,
    TierConfigListCreateView, TierConfigDetailView,
)

urlpatterns = [
    # ── Tiers de fidelización ─────────────────────────────────
    path("tiers/",            TierConfigListCreateView.as_view(), name="tier_configs"),
    path("tiers/<int:pk>/",   TierConfigDetailView.as_view(),     name="tier_config_detail"),

    # ── Clientes ──────────────────────────────────────────────
    path("",                    ClienteListCreateView.as_view(), name="clientes"),
    path("simple/",             ClienteSimpleListView.as_view(), name="clientes_simple"),
    path("<int:pk>/",           ClienteDetailView.as_view(),     name="cliente_detail"),
    path("<int:pk>/resumen/",   ClienteResumenView.as_view(),    name="cliente_resumen"),
    path("<int:pk>/creditos/",  CreditosClienteView.as_view(),   name="cliente_creditos"),

    # ── Separados — rutas fijas ANTES que las dinámicas ───────
    path("separados/",          SeparadoListCreateView.as_view(), name="separados"),
    path("separados/alertas/",        AlertasSeparadosView.as_view(),        name="alertas_separados"),
    path("separados/abonos/",         AbonosPorFechaView.as_view(),          name="abonos_por_fecha"),
    path("separados/recordatorios/",  RecordatoriosSeparadosView.as_view(),  name="recordatorios_separados"),

    # ── Separados — rutas dinámicas con <int:pk> ──────────────
    path("separados/<int:pk>/",          SeparadoDetailView.as_view(),    name="separado_detail"),
    path("separados/<int:pk>/abonar/",   AbonarSeparadoView.as_view(),    name="abonar_separado"),
    path("separados/<int:pk>/cancelar/",         CancelarSeparadoView.as_view(),         name="cancelar_separado"),
    path("separados/<int:pk>/cambiar-producto/", CambiarProductoSeparadoView.as_view(),  name="cambiar_producto_separado"),
]