"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include


urlpatterns = [
    path('admin/', admin.site.urls),
    path("api/auth/",      include("usuarios.urls")),
    path("api/tiendas/", include("tiendas.urls")),
    path("api/productos/", include("productos.urls")),
    path("api/proveedores/", include("proveedores.urls")),
    path("api/clientes/", include("clientes.urls")),
    path("api/caja/", include("caja.urls")),
    path("api/ventas/", include("ventas.urls")),
    path("api/devoluciones/",  include("devoluciones.urls")),
    path("api/contabilidad/",  include("contabilidad.urls")),
    path('api/empresas/', include('empresas.urls')),
]
