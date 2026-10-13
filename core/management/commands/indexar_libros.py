"""Construye el índice local sin consultar APIs ni consumir créditos."""
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from core.local_rag import index_documents


class Command(BaseCommand):
    help = 'Indexa una colección compartida PDF/TXT/MD con nombres Titulo__Autor.'

    def add_arguments(self, parser):
        parser.add_argument('--carpeta', default=str(Path(settings.BASE_DIR) / 'data' / 'libros'))
        parser.add_argument('--semantico', action='store_true',
                            help='Construye embeddings descargados en Ollama; no usa APIs de pago.')

    def handle(self, *args, **options):
        try:
            embedder = None
            if options.get('semantico'):
                from core.local_embeddings import configured_embedder
                embedder = configured_embedder(settings)
                if embedder is None:
                    raise ValueError('Activa LITMATE_RAG_SEMANTIC para usar --semantico')
            books, chunks = index_documents(options['carpeta'], settings.LITMATE_RAG_DB,
                embedder=embedder,
                progress=lambda n: self.stdout.write(f'Procesados {n} fragmentos...'))
        except Exception as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(self.style.SUCCESS(f'Colección indexada: {books} libros, {chunks} fragmentos.'))
        self.stdout.write('Solo se indexó texto. Las imágenes de PDF escaneados necesitan OCR previo.')
        self.stdout.write('Modo: ' + ('híbrido, con embeddings locales' if embedder else 'búsqueda por palabras'))
