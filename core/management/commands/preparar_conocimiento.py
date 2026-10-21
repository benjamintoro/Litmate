"""Instala fichas originales y su índice separado, sin tocar novelas del usuario."""
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.literary_knowledge import prepare_seed_knowledge, _records, knowledge_sources
from core.local_rag import index_documents


class Command(BaseCommand):
    help = 'Prepara fichas originales con referencias; --semantico usa embeddinggemma local.'

    def add_arguments(self, parser):
        parser.add_argument('--semantico', action='store_true')
        parser.add_argument('--base', default='', help='Ruta SQLite alternativa para las fichas.')
        parser.add_argument('--indice', default='', help='Índice separado de la colección de novelas.')

    def handle(self, *args, **options):
        database = Path(options.get('base') or settings.LITMATE_KNOWLEDGE_DB).resolve()
        index = Path(options.get('indice') or settings.LITMATE_KNOWLEDGE_RAG_DB).resolve()
        user_index = Path(settings.LITMATE_RAG_DB).resolve()
        if index == user_index or index == database:
            raise CommandError('El índice de fichas debe estar separado de la colección y de las fichas.')
        try:
            # Solo reconstruimos el índice gestionado por este comando. Una
            # base desconocida puede contener datos del usuario y se preserva.
            if index.is_file():
                with closing(sqlite3.connect(index.as_uri() + '?mode=ro', uri=True)) as db:
                    marker = db.execute('SELECT value FROM rag_metadata WHERE key=?',
                                        ('managed_by',)).fetchone()
                if not marker or marker[0] != 'preparar_conocimiento':
                    raise ValueError('El índice indicado no pertenece a preparar_conocimiento; usa una ruta nueva.')
            works = prepare_seed_knowledge(database)
            embedder = None
            if options.get('semantico'):
                from core.local_embeddings import configured_embedder
                embedder = configured_embedder(settings)
                if embedder is None:
                    raise ValueError('Activa LITMATE_RAG_SEMANTIC para usar --semantico')
            all_works, all_facts = _records(database)
            with tempfile.TemporaryDirectory(prefix='litmate-fichas-') as staging:
                folder, metadata = Path(staging), {}
                for work in all_works:
                    facts = [fact for fact in all_facts if fact['work_id'] == work['work_id']]
                    for number, source in enumerate(knowledge_sources(work, facts)[1:], 1):
                        # Los metadatos conservan la identidad: el nombre solo
                        # es una etiqueta local segura para Windows.
                        filename = work['work_id'].split(':')[-1] + f'-{number}__Ficha.txt'
                        (folder / filename).write_text(source['description'], encoding='utf-8')
                        metadata[filename] = {**source, 'indexing_authorized': True,
                                              'source': 'Biblioteca literaria local'}
                count, chunks = index_documents(folder, index, embedder=embedder, metadata=metadata)
            with closing(sqlite3.connect(index)) as db, db:
                db.execute('INSERT OR REPLACE INTO rag_metadata VALUES (?,?)',
                           ('managed_by', 'preparar_conocimiento'))
        except Exception as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(self.style.SUCCESS(
            f'Fichas verificables preparadas: {len(works)} iniciales; {count} documentos, {chunks} fragmentos.'))
        self.stdout.write('Modo: ' + ('híbrido con embeddings locales' if embedder else 'búsqueda por palabras'))
        self.stdout.write('Son resúmenes originales, no texto íntegro ni citas de las novelas.')
