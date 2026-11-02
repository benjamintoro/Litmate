"""Proyección administrativa del outbox admitido, sin consultas a Internet."""
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = 'Proyecta metadatos admitidos del ledger existente a MySQL local, por lotes reanudables.'

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--state-db', type=Path)
        mode.add_argument('--conflicts', action='store_true')
        mode.add_argument('--review-version')
        parser.add_argument('--record-id')
        parser.add_argument('--evidence-url')
        parser.add_argument('--operator-confirmed', action='store_true')
        parser.add_argument('--max-records', type=int, default=100)
        parser.add_argument('--batch-size', type=int, default=25)
        parser.add_argument('--max-seconds', type=float, default=30)
        parser.add_argument('--max-storage-mb', type=int, default=64)
        parser.add_argument('--replay', action='store_true')

    def handle(self, *args, **options):
        config = connection.settings_dict
        if (connection.vendor != 'mysql' or config.get('HOST') not in {'127.0.0.1', 'localhost'}
                or config.get('NAME') != 'litmate_db'):
            raise CommandError('Selecciona explícitamente MySQL local; no se escribe en TiDB ni en otros destinos.')
        from core.bibliographic_repository import project_ledger
        try:
            if options['conflicts']:
                from core.knowledge_models import KBRecord
                report = {'conflicts': [{'id':record.pk, 'label':record.label, 'source_url':record.source_url,
                    'versions':list(record.versions.filter(payload__has_key='source_url').values(
                        'id','checksum','source_revision')[:20])} for record in KBRecord.objects.filter(status='conflict')[:50]]}
            elif options['review_version']:
                from core.bibliographic_repository import review_version
                report = review_version(options['record_id'], options['review_version'],
                    evidence_url=options['evidence_url'], operator_confirmed=options['operator_confirmed'])
            else:
                report = project_ledger(options['state_db'], max_records=options['max_records'],
                    batch_size=options['batch_size'], max_seconds=options['max_seconds'],
                    max_storage_mb=options['max_storage_mb'], replay=options['replay'])
            self.stdout.write(json.dumps(report, ensure_ascii=False))
        except Exception as error:
            raise CommandError('La proyección se detuvo de forma segura: ' + type(error).__name__) from None
