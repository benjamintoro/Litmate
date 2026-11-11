"""Consola operativa de lectura; no concede permisos ni muestra chats privados."""
import json
from pathlib import Path
import shutil
from django.conf import settings
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import User
from django.template.response import TemplateResponse
from django.urls import path
from .admin import OperationalReadOnlyAdmin, ReaderUserAdmin, UsageAdmin, QueryAdmin, PaymentAdmin
from .models import UsageBucket, QueryOperation, PaymentEvent, SocialReport
from .social_admin import SocialReportAdmin
from .operations import account_health
from .auth_limits import auth_limit
from suscripciones.models import PlanSuscripcion, SuscripcionUsuario, HistorialPago


class OperationsSite(admin.AdminSite):
    site_header = 'LitMate · Operación'
    site_title = 'Operación LitMate'
    index_title = 'Estado y metadatos autorizados'
    enable_nav_sidebar = False

    def login(self, request, extra_context=None):
        return auth_limit(6)(super().login)(request, extra_context)

    def get_log_entries(self, request):
        # No consulta logs históricos del catálogo ni necesita una tabla nueva.
        return LogEntry.objects.none()

    def get_urls(self):
        return [path('estado/', self.admin_view(self.status), name='operations_status'), *super().get_urls()]

    def status(self, request):
        # Ver estado exige permiso explícito de cuotas además de is_staff.
        if not request.user.has_perm('reader_accounts.view_usagebucket'):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        config = settings.PRODUCTION
        reports = {}
        for name, file in [('startup', config.runtime/'startup.json'),
                           ('backup', config.root/'backups/automatic/latest.json'),
                           ('backup_failure', config.root/'backups/automatic/failure.json')]:
            try:
                raw = json.loads(file.read_text(encoding='utf8'))
                reports[name] = {k: raw[k] for k in ('ready','errors','warnings','services','status','at','restore_verified','error_class') if k in raw}
            except (OSError, ValueError):
                reports[name] = {'status': 'no_report'}
        context = {**self.each_context(request), 'title':'Estado operativo',
            'version':settings.LITMATE_VERSION, 'environment':settings.LITMATE_ENVIRONMENT,
            'health':account_health(config.accounts), 'reports':reports,
            'free_gib':round(shutil.disk_usage(config.runtime).free/1024**3, 2)}
        return TemplateResponse(request, 'admin/operations_status.html', context)


class ContactAdmin(OperationalReadOnlyAdmin):
    list_display = ('id', 'nombre', 'email', 'fecha_envio', 'leido')
    readonly_fields = ('nombre', 'email', 'telefono', 'mensaje', 'fecha_envio', 'leido')
    fields = readonly_fields
    search_fields = ('nombre', 'email')
    list_filter = ('leido',)


site = OperationsSite(name='operations')
from core.models import MensajeContacto
site.register(MensajeContacto, ContactAdmin)
site.register(SocialReport, SocialReportAdmin)
for model, cls in [(User,ReaderUserAdmin),(UsageBucket,UsageAdmin),
                   (QueryOperation,QueryAdmin),(PaymentEvent,PaymentAdmin)]:
    site.register(model, cls)


class PlanAdmin(OperationalReadOnlyAdmin):
    fields = ('nombre','slug','precio','moneda','periodo','limite_consultas_ia_diarias','activo')
    readonly_fields = list_display = fields


class SubscriptionAdmin(OperationalReadOnlyAdmin):
    fields = ('id','usuario_id','plan','estado','fecha_inicio','fecha_fin','auto_renovar')
    readonly_fields = list_display = fields


class HistoryAdmin(OperationalReadOnlyAdmin):
    fields = ('id','usuario_id','plan','monto','moneda','estado','fecha_pago')
    readonly_fields = list_display = fields


site.register(PlanSuscripcion, PlanAdmin)
site.register(SuscripcionUsuario, SubscriptionAdmin)
site.register(HistorialPago, HistoryAdmin)
