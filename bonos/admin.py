from django.contrib import admin
from .models import Bono, UsoBono

@admin.register(Bono)
class BonoAdmin(admin.ModelAdmin):
    list_display  = ['codigo', 'empresa', 'tienda_origen', 'valor_original', 'saldo', 'estado', 'fecha_vencimiento']
    list_filter   = ['estado', 'empresa']
    search_fields = ['codigo']
    readonly_fields = ['codigo', 'created_at']

@admin.register(UsoBono)
class UsoBonoAdmin(admin.ModelAdmin):
    list_display = ['bono', 'tienda', 'monto_usado', 'saldo_antes', 'saldo_despues', 'created_at']
    readonly_fields = ['created_at']
