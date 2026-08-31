from django.contrib import admin
from .models import PlanSuscripcion, SuscripcionUsuario, HistorialPago


@admin.register(PlanSuscripcion)
class PlanSuscripcionAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'slug', 'precio', 'moneda', 'periodo', 'limite_consultas_ia_diarias', 'acceso_ia_avanzada', 'activo', 'orden')
    list_editable = ('activo', 'orden')
    list_filter = ('activo', 'periodo', 'acceso_ia_avanzada')
    search_fields = ('nombre', 'slug', 'descripcion')
    prepopulated_fields = {'slug': ('nombre',)}


@admin.register(SuscripcionUsuario)
class SuscripcionUsuarioAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'plan', 'estado', 'fecha_inicio', 'fecha_fin', 'auto_renovar', 'es_valida')
    list_filter = ('estado', 'plan', 'auto_renovar', 'fecha_inicio')
    search_fields = ('usuario__username', 'usuario__email', 'id_suscripcion_externa')
    readonly_fields = ('fecha_inicio',)


@admin.register(HistorialPago)
class HistorialPagoAdmin(admin.ModelAdmin):
    list_display = ('id', 'usuario', 'plan', 'monto', 'moneda', 'metodo_pago', 'estado', 'fecha_pago')
    list_filter = ('estado', 'moneda', 'metodo_pago', 'fecha_pago')
    search_fields = ('usuario__username', 'referencia_transaccion')
    readonly_fields = ('fecha_pago',)
