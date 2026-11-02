"""Índice derivado local; nunca reemplaza la biblioteca ni documentos personales."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.literary_library import export_rag, library_status
from core.local_rag import index_documents
from core.ai_budget import request_budget


class Command(BaseCommand):
    help = 'Exporta e indexa una biblioteca autorizada; embeddings opcionales ya instalados en Ollama.'

    def add_arguments(self, parser):
        root = Path(settings.BASE_DIR) / 'data' / 'biblioteca'
        parser.add_argument('--base', default=str(root / 'biblioteca.sqlite3'))
        parser.add_argument('--indice', default=str(root / 'biblioteca_rag.sqlite3'))
        parser.add_argument('--exportar', default=str(root / 'rag_export'))
        parser.add_argument('--semantico', action='store_true')
        parser.add_argument('--simular', action='store_true')
        parser.add_argument('--max-segundos', type=float, default=1800,
                            help='Presupuesto total cooperativo; los lotes confirmados se reanudan.')
        parser.add_argument('--cache-vectores', help='SQLite auxiliar exclusiva; por defecto junto al índice.')
        parser.add_argument('--sin-cache-vectores', action='store_true')
        parser.add_argument('--max-cache-mb', type=int, default=256)

    def handle(self, *args, **options):
        started = time.monotonic()
        try:
            database, index = Path(options['base']).resolve(), Path(options['indice']).resolve()
            if database == index:
                raise ValueError('El índice derivado no puede reemplazar la biblioteca original')
            protected = [Path(value['NAME']).resolve() for value in settings.DATABASES.values()
                         if value.get('NAME') and value['NAME'] != ':memory:']
            for name in dir(settings):
                if name.startswith('LITMATE_') and name.endswith('_DB') and 'LIBRARY' not in name:
                    value = getattr(settings, name, None)
                    if value:
                        protected.append(Path(value).resolve())
            if index in protected:
                raise ValueError('El índice de biblioteca debe usar una base auxiliar propia')
            if index.is_file():
                with closing(sqlite3.connect(index.as_uri() + '?mode=ro', uri=True)) as db:
                    try:
                        owner = db.execute('SELECT source FROM library_index_owner WHERE id=1').fetchone()
                    except sqlite3.Error:
                        owner = None
                if owner != (str(database),):
                    raise ValueError('El destino no es un índice derivado gestionado de esta biblioteca')
            status = library_status(database)
            if not status['exists'] or not status['active']:
                raise ValueError('Importa primero originales autorizados a la biblioteca')
            if options['simular']:
                result = {'dry_run': True, 'books': status['active'], 'source_chunks': status['chunks']}
            else:
                if not 0 < options['max_segundos'] <= 86400:
                    raise ValueError('El presupuesto debe estar entre cero y 86400 segundos')
                vector_cache = None
                if options['semantico'] and not options['sin_cache_vectores']:
                    vector_cache = options['cache_vectores'] or str(index) + '.vectors.sqlite3'
                with request_budget(started + options['max_segundos']):
                    embedder = None
                    if options['semantico']:
                        from core.local_embeddings import configured_embedder
                        embedder = configured_embedder(settings)
                        if embedder is None:
                            raise ValueError('Activa LITMATE_RAG_SEMANTIC para usar embeddings locales')
                        embedder.identity()  # Comprueba modelo local antes de escribir derivados.
                    metadata = export_rag(database, options['exportar'])
                    books, chunks = index_documents(options['exportar'], index,
                        metadata=metadata, embedder=embedder, vector_cache=vector_cache,
                        vector_cache_max_bytes=options['max_cache_mb'] * 1_000_000)
                with closing(sqlite3.connect(index)) as db, db:
                    db.execute('CREATE TABLE IF NOT EXISTS library_index_owner'
                               '(id INTEGER PRIMARY KEY,source TEXT)')
                    db.execute('INSERT OR REPLACE INTO library_index_owner VALUES(1,?)',
                               (str(database),))
                result = {'dry_run': False, 'books': books, 'chunks': chunks,
                    'mode': 'hybrid' if embedder else 'lexical', 'index': str(index),
                    'vector_cache': str(vector_cache) if vector_cache else None,
                    'seconds': round(time.monotonic() - started, 6)}
        except (OSError, ValueError, sqlite3.Error, TimeoutError) as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
