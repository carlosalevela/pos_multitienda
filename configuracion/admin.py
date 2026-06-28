from django.contrib import admin
from .models import ConfigTienda, ConfigImpresion


@admin.register(ConfigTienda)
class ConfigTiendaAdmin(admin.ModelAdmin):
    list_display  = ["tienda", "moneda_simbolo", "iva_pct", "habilitar_mayoreo", "updated_at"]
    list_filter   = ["habilitar_mayoreo", "politica_cancelacion"]
    search_fields = ["tienda__nombre"]


@admin.register(ConfigImpresion)
class ConfigImpresionAdmin(admin.ModelAdmin):
    list_display  = ["tienda", "tipo_papel", "copias", "mostrar_logo", "updated_at"]
    list_filter   = ["tipo_papel", "mostrar_logo"]
    search_fields = ["tienda__nombre"]
