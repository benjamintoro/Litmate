"""Importación de originales revisados sin migraciones ni servicios de pago."""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.literary_library import (export_rag, import_manifest, library_status,
                                   read_gutenberg_rdf, retract_document)


class Command(BaseCommand):
    help = 'Biblioteca auxiliar TXT/EPUB autorizada en Chile; importación explícita y acotada.'

    def add_arguments(self, parser):
        root = Path(settings.BASE_DIR) / 'data' / 'biblioteca'
        parser.add_argument('--manifiesto', help='JSON version:1 con books, SHA256 y derechos CL revisados.')
        parser.add_argument('--base', default=str(root / 'biblioteca.sqlite3'))
        parser.add_argument('--almacen', default=str(root))
        parser.add_argument('--simular', action='store_true', help='Valida sin escribir ni descargar.')
        parser.add_argument('--descargar', action='store_true', help='Permite descargas de espejos oficiales.')
        parser.add_argument('--max-libros', type=int, default=10)
        parser.add_argument('--max-mb', type=int, default=250)
        parser.add_argument('--max-segundos', type=float, default=120)
        parser.add_argument('--estado', action='store_true', help='Sólo lectura de estadísticas.')
        parser.add_argument('--exportar', help='Carpeta gestionada para exportación compatible con RAG.')
        parser.add_argument('--retractar', help='ID de documento que debe retirarse del índice.')
        parser.add_argument('--motivo', default='')
        parser.add_argument('--catalogo-rdf', help='RDF oficial local: descubre candidatos, no autoriza textos.')
        parser.add_argument('--idiomas', default='es,en')
        parser.add_argument('--pausa-archivo', help='Detiene el lote entre documentos si este archivo existe.')

    def handle(self, *args, **options):
        try:
            database = Path(options['base']).resolve()
            protected = [Path(value['NAME']).resolve() for value in settings.DATABASES.values()
                         if value.get('NAME') and value['NAME'] != ':memory:']
            for setting in ('LITMATE_RAG_DB', 'LITMATE_KNOWLEDGE_DB', 'LITMATE_KNOWLEDGE_RAG_DB',
                            'LITMATE_LITERARY_MEMORY_DB', 'LITMATE_AI_RUNTIME_DB'):
                value = getattr(settings, setting, None)
                if value:
                    protected.append(Path(value).resolve())
            if database in protected:
                raise ValueError('La biblioteca debe usar una base auxiliar propia')
            if options['catalogo_rdf']:
                result = list(read_gutenberg_rdf(options['catalogo_rdf'],
                    languages=tuple(options['idiomas'].split(',')), maximum=options['max_libros']))
            elif options['estado']:
                result = library_status(database)
            elif options['simular'] and (options['exportar'] or options['retractar']):
                raise ValueError('--simular sólo valida manifiestos; no exporta ni retracta')
            elif options['retractar']:
                result = {'retracted': retract_document(options['retractar'], database,
                                                       reason=options['motivo'])}
            elif options['exportar']:
                result = {'exported': len(export_rag(database, options['exportar']))}
            elif options['manifiesto']:
                pause = Path(options['pausa_archivo']) if options['pausa_archivo'] else None
                result = import_manifest(options['manifiesto'], database, options['almacen'],
                    dry_run=options['simular'], download=options['descargar'],
                    max_books=options['max_libros'], max_total_bytes=options['max_mb'] * 1_000_000,
                    max_seconds=options['max_segundos'], stop=(lambda: pause.exists()) if pause else None)
            else:
                raise ValueError('Indica --manifiesto, --estado, --exportar, --retractar o --catalogo-rdf')
        except (OSError, ValueError, KeyError) as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
