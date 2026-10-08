from django.contrib import admin
from .models import ConfigTienda, ConfigImpresion, WhatsAppConfig, WhatsAppDestinatario


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


@admin.register(WhatsAppConfig)
class WhatsAppConfigAdmin(admin.ModelAdmin):
    list_display  = ["empresa", "phone_number_id", "activo", "updated_at"]
    list_filter   = ["activo"]
    search_fields = ["empresa__nombre"]


@admin.register(WhatsAppDestinatario)
class WhatsAppDestinatarioAdmin(admin.ModelAdmin):
    list_display  = ["nombre", "numero", "empresa", "activo"]
    list_filter   = ["activo", "empresa"]
    search_fields = ["nombre", "numero"]
    filter_horizontal = ["tiendas"]
