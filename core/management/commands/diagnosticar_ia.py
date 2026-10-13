"""Diagnóstico sin conexiones por defecto; Books y Ollama se prueban por separado."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from core.ai_http import local_origin, read_json_url
from core.books_google import BooksUnavailable, public_query, search_volumes
from core.literary_ai import build_assistant, ProviderUnavailable


class Command(BaseCommand):
    help = ('Revisa la IA sin conexiones. --books-live prueba solo Google Books; '
            '--live comprueba Ollama y una respuesta completa.')

    def add_arguments(self, parser):
        live = parser.add_mutually_exclusive_group()
        live.add_argument('--live', action='store_true')
        live.add_argument('--books-live', action='store_true')
        parser.add_argument('--sin-fuentes', action='store_true')
        parser.add_argument('--message', default='Recomiéndame un libro sobre guerra')

    def books_configuration(self):
        enabled = getattr(settings, 'LITMATE_USE_GOOGLE_BOOKS_API', True)
        key = str(getattr(settings, 'GOOGLE_BOOKS_API_KEY', '')).strip()
        configured = bool(key) and not key.startswith(('tu_', 'YOUR_'))
        if not enabled:
            self.stdout.write('Google Books API: desactivada (disabled).')
        elif not configured:
            self.stdout.write('Google Books API: activada, falta una clave válida (missing_key).')
        else:
            self.stdout.write('Google Books API: activada; clave configurada, valor oculto.')
        self.stdout.write('Google Books aporta fichas y sinopsis; no garantiza el texto completo de una obra.')

    def check_books(self, message, *, required=False):
        query = public_query(message)
        if not query:
            error = 'invalid_query'
        else:
            try:
                items = search_volumes(query, max_results=3)
                self.stdout.write(f'Google Books: conexión correcta; {len(items)} fichas recibidas.')
                return
            except BooksUnavailable as exc:
                error = exc.code
            except Exception:
                # Los mensajes de las librerías HTTP pueden incluir la URL con la clave.
                error = 'unavailable'
        explanations = {
            'disabled': 'Configura LITMATE_USE_GOOGLE_BOOKS_API=True en .env.',
            'missing_key': 'Activa Books API en Google Cloud y configura GOOGLE_BOOKS_API_KEY en .env.',
            'invalid_key': 'Revisa GOOGLE_BOOKS_API_KEY y las restricciones de la clave en Google Cloud.',
            'access_or_quota': 'Revisa la activación de Books API, restricciones y cuotas en Google Cloud.',
            'quota_exceeded': 'Se agotó la cuota; revisa las cuotas de Books API en Google Cloud.',
            'invalid_query': 'Usa --message con un título, autor, tema o ISBN válido; no incluyas un pasaje privado.',
            'invalid_response': 'Google devolvió una respuesta inesperada; vuelve a probar.',
            'unavailable': 'Comprueba tu conexión a internet y vuelve a probar.',
        }
        text = 'Google Books: ' + error + '. ' + explanations.get(error, 'Vuelve a probar la consulta.')
        if required:
            raise CommandError(text)
        self.stdout.write(text)

    def handle(self, *args, **options):
        self.books_configuration()
        if options.get('books_live'):
            self.check_books(options['message'], required=True)
            return
        assistant, client = build_assistant(settings,
            search=(lambda query: []) if options['sin_fuentes'] else None,
            web_search=(lambda query: []) if options['sin_fuentes'] else None)
        self.stdout.write('Proveedor: Ollama local, sin clave de IA.')
        self.stdout.write('Modelo: ' + assistant.answer_model)
        self.stdout.write('Revisión: ' + assistant.guard_model)
        self.stdout.write('Contexto: ' + str(client.context) + ' tokens locales.')
        self.stdout.write('Plan y auditoría de cobertura: ' + ('activados' if assistant.quality_checks else 'desactivados'))
        self.stdout.write('Recomendaciones habituales: ' + ('ruta rápida con revisión' if assistant.fast_recommendations
                                                          else 'plan y auditoría completos'))
        self.stdout.write('Presupuesto por consulta: ' + str(getattr(settings, 'LITMATE_AI_TOTAL_TIMEOUT', 300)) + ' s.')
        self.stdout.write('Buscador: ' + ('SearXNG + Wikipedia' if getattr(
            settings, 'LITMATE_AI_USE_SEARXNG', True) else 'Wikipedia; SearXNG desactivado'))
        self.stdout.write('Contenido: colección local PDF/TXT/MD; embeddings opcionales.')
        try:
            local_origin(client.base_url)
            local_origin(getattr(settings, 'LITMATE_SEARXNG_URL', 'http://127.0.0.1:8080'))
        except ValueError as exc:
            raise CommandError(str(exc)) from None
        if not options['live']:
            self.stdout.write('Configuración revisada; no se hicieron conexiones. '
                              'Usa --books-live para Google Books o --live para Ollama y una respuesta.')
            return
        if not options['sin_fuentes']:
            self.check_books(options['message'])
        try:
            client.inspect_model(assistant.answer_model)
            client.inspect_model(assistant.guard_model)
        except ProviderUnavailable as exc:
            raise CommandError(exc.code + '. Abre Ollama y ejecuta: ollama pull ' + assistant.answer_model) from None
        from pathlib import Path
        import sqlite3
        from contextlib import closing
        database = Path(getattr(settings, 'LITMATE_RAG_DB', Path(settings.BASE_DIR) / 'data' / 'litmate_rag.sqlite3'))
        if database.is_file():
            try:
                with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                    total = db.execute('SELECT count(*) FROM chunks').fetchone()[0]
                    metadata = dict(db.execute('SELECT key,value FROM rag_metadata'))
                self.stdout.write(f'RAG: {total} fragmentos; ' + ('híbrido' if metadata.get('model') else 'léxico'))
                if metadata.get('model'):
                    from core.local_embeddings import configured_embedder
                    embedder = configured_embedder(settings)
                    if embedder is None:
                        self.stdout.write('Embeddings desactivados; se usará búsqueda por palabras.')
                    elif embedder.identity() != (metadata.get('model'), metadata.get('digest')):
                        self.stdout.write('El modelo del índice cambió: ejecuta indexar_libros --semantico otra vez.')
                    else:
                        embedder.embed(['personajes de una novela'], query=True)
                        self.stdout.write('Embeddings locales: responden y coinciden con el índice.')
            except Exception as exc:
                self.stdout.write('RAG requiere revisión: ' + type(exc).__name__ + '. Comprueba Ollama e indexa de nuevo.')
        else:
            self.stdout.write('RAG sin colección: aún puedes conversar; agrega libros para analizar sus pasajes reales.')
        if not options['sin_fuentes'] and getattr(settings, 'LITMATE_AI_USE_SEARXNG', True):
            try:
                origin = local_origin(getattr(settings, 'LITMATE_SEARXNG_URL', 'http://127.0.0.1:8080'))
                read_json_url(origin + '/search?q=libros&format=json&engines=google,duckduckgo',
                              local=True, timeout=15)
                self.stdout.write('SearXNG: responde en JSON.')
            except Exception:
                self.stdout.write('SearXNG: no disponible. Ejecuta python iniciar_buscador.py; Wikipedia sigue como respaldo.')
        result = assistant.reply(options['message'])
        self.stdout.write('\nEstado: ' + result.status + '\n' + result.text)
        self.stdout.write('\nTokens locales, solo estadística: ' + str(client.usage))
        self.stdout.write('Llamadas al modelo local: ' + str(client.calls))
        self.stdout.write('Diagnóstico: ' + str(result.diagnostics))
        if result.status == 'unavailable':
            raise CommandError('No se pudo completar la respuesta local.')
