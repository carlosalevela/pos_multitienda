from django.urls import path
from .views import (
    ClienteListCreateView, ClienteDetailView, ClienteSimpleListView,
    SeparadoListCreateView, SeparadoDetailView,
    AbonarSeparadoView, CancelarSeparadoView,
    AlertasSeparadosView, AbonosPorFechaView,
)

urlpatterns = [
    # ── Clientes ──────────────────────────────────────────────
    path("",          ClienteListCreateView.as_view(), name="clientes"),
    path("simple/",   ClienteSimpleListView.as_view(), name="clientes_simple"),
    path("<int:pk>/", ClienteDetailView.as_view(),     name="cliente_detail"),

    # ── Separados — rutas fijas ANTES que las dinámicas ───────
    path("separados/",          SeparadoListCreateView.as_view(), name="separados"),
    path("separados/alertas/",  AlertasSeparadosView.as_view(),   name="alertas_separados"),   # ✅ subió
    path("separados/abonos/",   AbonosPorFechaView.as_view(),     name="abonos_por_fecha"),    # ✅ nombre y subió

    # ── Separados — rutas dinámicas con <int:pk> ──────────────
    path("separados/<int:pk>/",          SeparadoDetailView.as_view(),    name="separado_detail"),
    path("separados/<int:pk>/abonar/",   AbonarSeparadoView.as_view(),    name="abonar_separado"),
    path("separados/<int:pk>/cancelar/", CancelarSeparadoView.as_view(),  name="cancelar_separado"),
]