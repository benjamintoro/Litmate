"""Una única configuración para búsqueda Google Books, IA local y RAG."""
import os
from pathlib import Path


def apply_ai_settings(target, base_dir):
    from core.ai_budget import CHAT_WORK_SECONDS

    def flag(name, default=True):
        return os.getenv(name, str(default)).lower() in {'1', 'true', 'yes', 'on'}
    model = os.getenv('LITMATE_LOCAL_MODEL', 'qwen3.5:9b-q4_K_M').strip()
    target.update(
        LITMATE_AI_PROVIDER='ollama-local', LITMATE_AI_USE_PINECONE=False,
        LITMATE_OLLAMA_URL=os.getenv('LITMATE_OLLAMA_URL', 'http://127.0.0.1:11434'),
        LITMATE_LOCAL_MODEL=model,
        LITMATE_LOCAL_GUARD_MODEL=os.getenv('LITMATE_LOCAL_GUARD_MODEL', model).strip(),
        LITMATE_LOCAL_TIMEOUT=int(os.getenv('LITMATE_LOCAL_TIMEOUT', '240')),
        LITMATE_LOCAL_CONTEXT=int(os.getenv('LITMATE_LOCAL_CONTEXT', '16384')),
        LITMATE_LOCAL_THINKING=flag('LITMATE_LOCAL_THINKING', False),
        LITMATE_LOCAL_ANSWER_TOKENS=int(os.getenv('LITMATE_LOCAL_ANSWER_TOKENS', '3072')),
        LITMATE_AI_TOTAL_TIMEOUT=int(os.getenv('LITMATE_AI_TOTAL_TIMEOUT', '360')),
        # El chat interactivo tiene un presupuesto propio, aunque un diagnóstico
        # offline necesite más tiempo. El trabajo del modelo queda acotado por
        # CHAT_WORK_SECONDS; la respuesta completa reserva unos segundos más
        # para guardar la sesión y cerrar el stream.
        LITMATE_CHAT_TIMEOUT=min(CHAT_WORK_SECONDS, max(.1, float(os.getenv(
            'LITMATE_CHAT_TIMEOUT', str(CHAT_WORK_SECONDS))))),
        # El descubrimiento externo compite con el modelo por el mismo reloj.
        # Seis segundos bastan para catálogo local y una fuente pública; si no
        # hay fichas, es mejor reservar el resto para razonar y verificar.
        LITMATE_AI_DISCOVERY_SECONDS=float(os.getenv('LITMATE_AI_DISCOVERY_SECONDS', '6')),
        LITMATE_AI_QUALITY_CHECKS=flag('LITMATE_AI_QUALITY_CHECKS'),
        LITMATE_AI_FAST_RECOMMENDATIONS=flag('LITMATE_AI_FAST_RECOMMENDATIONS'),
        LITMATE_AI_SEARCH_BUDGET=int(os.getenv('LITMATE_AI_SEARCH_BUDGET', '4')),
        LITMATE_AI_REQUESTS_PER_MINUTE=int(os.getenv('LITMATE_AI_REQUESTS_PER_MINUTE', '20')),
        LITMATE_USE_EXISTING_QUOTAS=flag('LITMATE_USE_EXISTING_QUOTAS', False),
        LITMATE_TRUST_X_FORWARDED_FOR=flag('LITMATE_TRUST_X_FORWARDED_FOR', False),
        LITMATE_TRUSTED_PROXY_IPS=tuple(x.strip() for x in os.getenv(
            'LITMATE_TRUSTED_PROXY_IPS', '').split(',') if x.strip()),
        LITMATE_AI_CATALOG_FALLBACK=flag('LITMATE_AI_CATALOG_FALLBACK'),
        LITMATE_AI_REQUIRE_BOOK_SOURCES=flag('LITMATE_AI_REQUIRE_BOOK_SOURCES'),
        LITMATE_AI_BIBLIOGRAPHIC_FAST_PATH=flag('LITMATE_AI_BIBLIOGRAPHIC_FAST_PATH'),
        LITMATE_AI_PUBLIC_DETAILS_FAST_PATH=flag('LITMATE_AI_PUBLIC_DETAILS_FAST_PATH'),
        LITMATE_AI_USE_OPENLIBRARY=flag('LITMATE_AI_USE_OPENLIBRARY'),
        LITMATE_AI_USE_WEB=flag('LITMATE_AI_USE_WEB'),
        LITMATE_AI_USE_SEARXNG=flag('LITMATE_AI_USE_SEARXNG', False),
        LITMATE_SEARXNG_URL=os.getenv('LITMATE_SEARXNG_URL', 'http://127.0.0.1:8080'),
        LITMATE_SEARXNG_ENGINES=tuple(x.strip() for x in os.getenv(
            'LITMATE_SEARXNG_ENGINES', 'wikipedia,openlibrary,mwmbl').split(',') if x.strip()),
        LITMATE_SEARXNG_WEB_ENGINES=tuple(x.strip() for x in os.getenv(
            'LITMATE_SEARXNG_WEB_ENGINES', 'mwmbl,duckduckgo').split(',') if x.strip()),
        LITMATE_RESEARCH_ENABLED=flag('LITMATE_RESEARCH_ENABLED'),
        LITMATE_RESEARCH_TIMEOUT=float(os.getenv('LITMATE_RESEARCH_TIMEOUT', '15')),
        LITMATE_RESEARCH_MAX_SEARCHES=int(os.getenv('LITMATE_RESEARCH_MAX_SEARCHES', '2')),
        LITMATE_RESEARCH_MAX_PAGES=int(os.getenv('LITMATE_RESEARCH_MAX_PAGES', '3')),
        LITMATE_RESEARCH_CACHE_SECONDS=int(os.getenv('LITMATE_RESEARCH_CACHE_SECONDS', '86400')),
        LITMATE_AI_USE_WIKIDATA=flag('LITMATE_AI_USE_WIKIDATA'),
        LITMATE_KNOWLEDGE_DB=Path(os.getenv('LITMATE_KNOWLEDGE_DB', str(Path(base_dir) / 'data' / 'litmate_knowledge.sqlite3'))),
        LITMATE_KNOWLEDGE_RAG_DB=Path(os.getenv('LITMATE_KNOWLEDGE_RAG_DB', str(Path(base_dir) / 'data' / 'litmate_knowledge_rag.sqlite3'))),
        # SQLite auxiliares: conocimiento público con procedencia y resultados
        # privados efímeros separados. No requieren migraciones de Django.
        LITMATE_LITERARY_MEMORY_DB=Path(os.getenv('LITMATE_LITERARY_MEMORY_DB', str(Path(base_dir) / 'data' / 'literary_memory.sqlite3'))),
        # Outcome categories only; no private prompts or user corrections as facts.
        LITMATE_AUTO_ENRICHMENT=flag('LITMATE_AUTO_ENRICHMENT', True),
        # Biblioteca local de originales autorizados y su índice derivado. Las
        # rutas son configurables para no mezclar corpus de distintas máquinas.
        LITMATE_LIBRARY_DB=Path(os.getenv('LITMATE_LIBRARY_DB', str(Path(base_dir) / 'data' / 'biblioteca' / 'biblioteca.sqlite3'))),
        LITMATE_LIBRARY_RAG_DB=Path(os.getenv('LITMATE_LIBRARY_RAG_DB', str(Path(base_dir) / 'data' / 'biblioteca' / 'rag.sqlite3'))),
        # La recuperación semántica de la biblioteca es opcional mientras no se
        # valide extremo a extremo la latencia y la calidad de respuesta.
        LITMATE_LIBRARY_SEMANTIC_CHAT=flag('LITMATE_LIBRARY_SEMANTIC_CHAT', False),
        LITMATE_AI_ANSWER_CACHE_DB=Path(os.getenv('LITMATE_AI_ANSWER_CACHE_DB', str(Path(base_dir) / 'data' / 'litmate_answers.sqlite3'))),
        LITMATE_AI_STREAM_DB=Path(os.getenv('LITMATE_AI_STREAM_DB', str(Path(base_dir) / 'data' / 'litmate_ia_stream.sqlite3'))),
        LITMATE_BOOKS_CONTACT=os.getenv('LITMATE_BOOKS_CONTACT', '').strip(),
        LITMATE_RAG_DB=Path(os.getenv('LITMATE_RAG_DB', str(Path(base_dir) / 'data' / 'litmate_rag.sqlite3'))),
        LITMATE_RAG_SEMANTIC=flag('LITMATE_RAG_SEMANTIC'),
        LITMATE_EMBED_MODEL=os.getenv('LITMATE_EMBED_MODEL', 'embeddinggemma:latest').strip(),
        LITMATE_EMBED_TIMEOUT=int(os.getenv('LITMATE_EMBED_TIMEOUT', '60')),
        LITMATE_RAG_MIN_SIMILARITY=float(os.getenv('LITMATE_RAG_MIN_SIMILARITY', '0.35')),
        # Books es opcional: no se infiere autorización económica de una clave vieja.
        LITMATE_API_COST_POLICY='local-and-public-free-only',
        LITMATE_GOOGLE_BOOKS_CONFIRMED_NO_BILLING=flag('LITMATE_GOOGLE_BOOKS_CONFIRMED_NO_BILLING', False),
        LITMATE_USE_GOOGLE_BOOKS_API=(flag('LITMATE_USE_GOOGLE_BOOKS_API') and
                                    flag('LITMATE_GOOGLE_BOOKS_CONFIRMED_NO_BILLING', False)),
        GOOGLE_BOOKS_API_KEY=os.getenv('GOOGLE_BOOKS_API_KEY', '').strip(),
        GOOGLE_BOOKS_TIMEOUT=int(os.getenv('GOOGLE_BOOKS_TIMEOUT', '8')),
        GOOGLE_BOOKS_LANGUAGE=os.getenv('GOOGLE_BOOKS_LANGUAGE', '').strip(),
        LITMATE_AI_LOCK_BACKEND=os.getenv('LITMATE_AI_LOCK_BACKEND', 'sqlite').strip().lower(),
        LITMATE_AI_RUNTIME_DB=Path(os.getenv('LITMATE_AI_RUNTIME_DB', str(Path(base_dir) / 'data' / 'litmate_ia_runtime.sqlite3'))),
        LITMATE_TTS_ENABLED=flag('LITMATE_TTS_ENABLED', False),
        LITMATE_TTS_TIMEOUT_SECONDS=int(os.getenv('LITMATE_TTS_TIMEOUT_SECONDS', '20')),
    )
    cache_url = os.getenv('CACHE_URL', '').strip()
    if cache_url:
        target['CACHES'] = {'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache',
                                     'LOCATION': cache_url}}
