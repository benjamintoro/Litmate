"""Construye el índice local sin consultar APIs ni consumir créditos."""
from pathlib import Path
import json
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from core.local_rag import index_documents


class Command(BaseCommand):
    help = 'Indexa una colección compartida PDF/TXT/MD con nombres Titulo__Autor.'

    def add_arguments(self, parser):
        parser.add_argument('--carpeta', default=str(Path(settings.BASE_DIR) / 'data' / 'libros'))
        parser.add_argument('--semantico', action='store_true',
                            help='Construye embeddings descargados en Ollama; no usa APIs de pago.')
        parser.add_argument('--metadatos', default='',
                            help='JSON local con licencia, procedencia y tipo de cada documento autorizado.')

    def handle(self, *args, **options):
        try:
            embedder = None
            if options.get('semantico'):
                from core.local_embeddings import configured_embedder
                embedder = configured_embedder(settings)
                if embedder is None:
                    raise ValueError('Activa LITMATE_RAG_SEMANTIC para usar --semantico')
            metadata = None
            if options.get('metadatos'):
                path = Path(options['metadatos'])
                if path.stat().st_size > 2_000_000:
                    raise ValueError('El manifiesto de metadatos supera 2 MB')
                metadata = json.loads(path.read_text(encoding='utf-8-sig'))
            books, chunks = index_documents(options['carpeta'], settings.LITMATE_RAG_DB,
                embedder=embedder,
                metadata=metadata,
                progress=lambda n: self.stdout.write(f'Procesados {n} fragmentos...'))
        except Exception as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(self.style.SUCCESS(f'Colección indexada: {books} libros, {chunks} fragmentos.'))
        self.stdout.write('Solo se indexó texto. Las imágenes de PDF escaneados necesitan OCR previo.')
        self.stdout.write('Modo: ' + ('híbrido, con embeddings locales' if embedder else 'búsqueda por palabras'))
