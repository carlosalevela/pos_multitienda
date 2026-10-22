from django.urls import path
from .views import (ConfigTiendaView, ConfigImpresionView, ConfigDefaultsView,
                    CuentaBancariaListView, CuentaBancariaDetailView, ResumenCuentasView,
                    AppVersionView)

urlpatterns = [
    path("defaults/",                                         ConfigDefaultsView.as_view(),     name="config_defaults"),
    path("tienda/<int:tienda_id>/",                           ConfigTiendaView.as_view(),        name="config_tienda"),
    path("impresion/<int:tienda_id>/",                        ConfigImpresionView.as_view(),     name="config_impresion"),
    # Cuentas bancarias / Nequi / DaviPlata
    path("cuentas/<int:tienda_id>/",                          CuentaBancariaListView.as_view(),  name="cuentas_list"),
    path("cuentas/<int:tienda_id>/resumen/",                  ResumenCuentasView.as_view(),      name="cuentas_resumen"),
    path("cuentas/<int:tienda_id>/<int:cuenta_id>/",          CuentaBancariaDetailView.as_view(),name="cuentas_detail"),
    path("version/",                                           AppVersionView.as_view(),          name="app_version"),
]
