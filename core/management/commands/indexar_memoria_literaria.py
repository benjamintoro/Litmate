"""Índice de memoria derivado; embeddings locales únicamente con opt-in."""
import hashlib
import json
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.ai_concurrency import acquire, release
from core.literary_memory_rag import build_memory_index, index_path


class Command(BaseCommand):
    help = ('Indexa fuentes públicas admitidas de la memoria en un SQLite separado. '
            'Por defecto sólo BM25; --semantic utiliza embeddings locales ya instalados.')

    def add_arguments(self, parser):
        parser.add_argument('--database', type=Path)
        parser.add_argument('--index', type=Path)
        parser.add_argument('--semantic', '--index-semantic', dest='semantic', action='store_true')
        parser.add_argument('--max-sources', type=int, default=5000)
        parser.add_argument('--max-seconds', type=float, default=300)

    def handle(self, *args, **options):
        if not 1 <= options['max_sources'] <= 5000 or not 1 <= options['max_seconds'] <= 300:
            raise CommandError('Usa --max-sources entre 1 y 5000 y --max-seconds entre 1 y 300.')
        owner = uuid.uuid4().hex
        locked, model_locked = False, False
        key = ''
        try:
            destination = index_path(options.get('index'), database=options.get('database'))
            key = 'litmate-memory-index:' + hashlib.sha256(str(destination).encode()).hexdigest()
            locked = acquire(key, owner, int(options['max_seconds']) + 60)
            if not locked:
                raise CommandError('Otro proceso está construyendo este índice; se conservó el destino.')
            embedder = None
            if options.get('semantic'):
                model_locked = acquire('litmate_local_inference_lock', owner, int(options['max_seconds']) + 60)
                if not model_locked:
                    raise CommandError('La IA local está ocupada; ejecuta el indexado semántico cuando quede libre.')
                from core.local_embeddings import configured_embedder
                embedder = configured_embedder(settings)
                if embedder is None:
                    raise CommandError('Los embeddings locales están deshabilitados; el modo BM25 sigue disponible.')
            report = build_memory_index(database=options.get('database'), index=destination,
                embedder=embedder, maximum=options['max_sources'], max_seconds=options['max_seconds'])
            self.stdout.write(json.dumps(report, ensure_ascii=False))
        except (OSError, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from None
        finally:
            if model_locked:
                release('litmate_local_inference_lock', owner)
            if locked:
                release(key, owner)
