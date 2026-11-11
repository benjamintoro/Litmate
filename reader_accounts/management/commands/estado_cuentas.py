"""Diagnóstico LOCAL de sólo lectura; no abre una ruta HTTP administrativa."""
import json
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from reader_accounts.operations import account_health


class Command(BaseCommand):
    help = 'Comprueba integridad y conteos agregados de la base de cuentas configurada, sin datos personales.'

    def handle(self, *args, **options):
        summary = account_health(settings.DATABASES['accounts']['NAME'])
        self.stdout.write(json.dumps(summary))
        if summary['status'] != 'ok':
            raise CommandError('El almacén no pasó la comprobación; no se modificó.')
