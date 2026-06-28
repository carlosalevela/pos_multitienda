from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/",            admin.site.urls),
    path("api/auth/",         include("usuarios.urls")),
    path("api/tiendas/",      include("tiendas.urls")),
    path("api/productos/",    include("productos.urls")),
    path("api/proveedores/",  include("proveedores.urls")),
    path("api/clientes/",     include("clientes.urls")),
    path("api/caja/",         include("caja.urls")),
    path("api/ventas/",       include("ventas.urls")),
    path("api/devoluciones/", include("devoluciones.urls")),
    path("api/contabilidad/", include("contabilidad.urls")),
    path("api/empresas/",     include("empresas.urls")),
    path("api/config/",       include("configuracion.urls")),
]
