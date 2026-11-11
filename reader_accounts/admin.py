"""Operación en Django Admin: metadatos mínimos, lectura y permisos existentes."""
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import User
from core.models import ConversacionIA, MensajeIA, HistorialChatbot, PerfilUsuario, LibroFavorito, EstadoLectura
from .models import UsageBucket, QueryOperation, PaymentEvent


class OperationalReadOnlyAdmin(admin.ModelAdmin):
    actions = None
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UsageBucket)
class UsageAdmin(OperationalReadOnlyAdmin):
    fields = ('id', 'period', 'used')
    readonly_fields = fields
    list_display = fields
    list_filter = ('period',)


@admin.register(QueryOperation)
class QueryAdmin(OperationalReadOnlyAdmin):
    fields = ('id', 'status', 'created_at', 'expires_at')
    readonly_fields = fields
    list_display = fields
    list_filter = ('status',)


@admin.register(PaymentEvent)
class PaymentAdmin(OperationalReadOnlyAdmin):
    fields = ('id', 'provider', 'created_at')
    readonly_fields = fields
    list_display = fields


if getattr(settings, 'LITMATE_ACCOUNTS_ENABLED', False):
    # No habilita /admin en el gateway. Si el operador utiliza otro acceso
    # administrativo autorizado, no verá mensajes/fotos/bibliotecas por defecto.
    for model in (ConversacionIA, MensajeIA, HistorialChatbot, PerfilUsuario, LibroFavorito, EstadoLectura, User):
        if admin.site.is_registered(model):
            admin.site.unregister(model)

    @admin.register(User)
    class ReaderUserAdmin(OperationalReadOnlyAdmin):
        fields = ('id', 'username', 'is_active', 'date_joined')
        readonly_fields = fields
        list_display = fields
        search_fields = ('username',)
