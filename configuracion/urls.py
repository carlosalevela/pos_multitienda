from django.urls import path
from .views import ConfigTiendaView, ConfigImpresionView, ConfigDefaultsView

urlpatterns = [
    path("defaults/",                    ConfigDefaultsView.as_view(),  name="config_defaults"),
    path("tienda/<int:tienda_id>/",      ConfigTiendaView.as_view(),    name="config_tienda"),
    path("impresion/<int:tienda_id>/",   ConfigImpresionView.as_view(), name="config_impresion"),
]
