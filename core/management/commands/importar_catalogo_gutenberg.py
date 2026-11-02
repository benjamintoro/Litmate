"""Importa el catálogo oficial, sin confundir metadatos y novelas."""
import json
import sqlite3
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Importa CSV(.gz)/RDF Gutenberg en streaming, con checkpoint y permisos sólo de metadatos.'

    def add_arguments(self, parser):
        parser.add_argument('--catalog', type=Path, required=True)
        parser.add_argument('--download-catalog', action='store_true')
        parser.add_argument('--state-db', type=Path, required=True)
        parser.add_argument('--database', type=Path, required=True)
        parser.add_argument('--max-records', type=int, default=1000)
        parser.add_argument('--max-scanned', type=int, default=100000)
        parser.add_argument('--max-seconds', type=float, default=120)
        parser.add_argument('--max-storage-mb', type=int, default=128)
        parser.add_argument('--language', action='append', default=[])
        parser.add_argument('--rdf', action='store_true')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        from core.literary_gutenberg import download_catalog, import_catalog
        try:
            if options['download_catalog']:
                if options['dry_run']:
                    raise ValueError('--dry-run no descarga archivos; indica un catálogo local.')
                self.stdout.write(json.dumps(download_catalog(options['catalog']), ensure_ascii=False))
            report = import_catalog(options['catalog'], state_database=options['state_db'],
                memory_database=options['database'], max_records=options['max_records'],
                max_scanned=options['max_scanned'], max_seconds=options['max_seconds'],
                max_storage_mb=options['max_storage_mb'], languages=options['language'] or ('es', 'en'),
                dry_run=options['dry_run'], rdf=options['rdf'])
            self.stdout.write(json.dumps(report, ensure_ascii=False))
        except (OSError, ValueError, sqlite3.Error) as error:
            raise CommandError(str(error)) from None
