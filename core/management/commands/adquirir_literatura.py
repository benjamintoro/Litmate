"""Importación bibliográfica explícita; nunca se inicia con Django."""
import json
import sqlite3
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.literary_acquisition import (acquisition_stats, drain_projection,
    import_bne_marcxml, import_openlibrary_dump, query_acquisition)


class Command(BaseCommand):
    help = ('Importa metadatos bibliográficos autorizados en un ledger y memoria auxiliares. '
            'Open Library masivo: sólo volcado oficial local; API: lookup humano limitado.')

    def add_arguments(self, parser):
        parser.add_argument('--state-db', type=Path, required=True)
        parser.add_argument('--database', type=Path, help='Memoria literaria SQLite auxiliar, no catálogo Django.')
        parser.add_argument('--provider', choices=('openlibrary', 'bne', 'wikidata', 'wikipedia'), default='openlibrary')
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--dump', type=Path, help='TSV(.gz) Open Library o MARCXML(.gz) BNE oficial local.')
        mode.add_argument('--query', help='Una búsqueda bibliográfica iniciada por una persona; máximo 5 obras.')
        mode.add_argument('--project', action='store_true', help='Reintenta la bandeja durable sin hacer red.')
        mode.add_argument('--stats', action='store_true', help='Lee estadísticas sin crear archivos.')
        parser.add_argument('--source-url', help='URL oficial del archivo, registrada como procedencia.')
        parser.add_argument('--sha256', default='')
        parser.add_argument('--title', default='', help='Identidad confirmada para Wikipedia.')
        parser.add_argument('--author', default='')
        parser.add_argument('--max-records', type=int, default=1000)
        parser.add_argument('--max-scanned', type=int, default=10000)
        parser.add_argument('--max-seconds', type=float, default=60)
        parser.add_argument('--max-storage-mb', type=int, default=64)
        parser.add_argument('--subject', action='append', default=[])
        parser.add_argument('--language', action='append', default=[])
        parser.add_argument('--dry-run', action='store_true', help='Valida/lee fuentes sin escribir ledger ni memoria.')
        parser.add_argument('--restart', action='store_true', help='Reinicia cursor; conserva registros deduplicados.')

    def handle(self, *args, **options):
        try:
            common = {'state_database': options['state_db'], 'memory_database': options.get('database')}
            if options['stats']:
                report = acquisition_stats(options['state_db'])
            elif options['project']:
                if options['dry_run']:
                    report = {'dry_run': True, 'network': False, 'stats': acquisition_stats(options['state_db'])}
                elif not options.get('database'):
                    raise ValueError('--project necesita --database auxiliar explícita.')
                else:
                    report = drain_projection(**common, max_records=options['max_records'],
                                              max_seconds=options['max_seconds'])
            elif options['dump']:
                if options['provider'] not in {'openlibrary', 'bne'} or not options['source_url']:
                    raise ValueError('--dump necesita proveedor openlibrary|bne y --source-url oficial.')
                importer = import_openlibrary_dump if options['provider'] == 'openlibrary' else import_bne_marcxml
                report = importer(options['dump'], **common, source_url=options['source_url'],
                    expected_sha256=options['sha256'], max_records=options['max_records'],
                    max_scanned=options['max_scanned'], max_seconds=options['max_seconds'],
                    max_storage_mb=options['max_storage_mb'], dry_run=options['dry_run'],
                    subjects=options['subject'], languages=options['language'], resume=not options['restart'])
            else:
                if options['provider'] == 'bne':
                    raise ValueError('BNE se importa desde MARCXML oficial local; no se raspa HTML.')
                book = {'title': options['title'], 'author': options['author']} if options['title'] else None
                report = query_acquisition(options['query'], **common, provider=options['provider'],
                    max_results=min(options['max_records'], 5), max_seconds=min(options['max_seconds'], 30),
                    dry_run=options['dry_run'], book=book)
            self.stdout.write(json.dumps(report, ensure_ascii=False))
        except KeyboardInterrupt:
            self.stdout.write('Adquisición pausada; los registros confirmados y checkpoints se conservan.')
        except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
            # No publicar mensajes de red que puedan contener URLs/credenciales.
            if isinstance(exc, (OSError, sqlite3.Error)):
                raise CommandError('No se pudo acceder de forma segura al archivo o ledger auxiliar.') from None
            raise CommandError(str(exc)) from None
