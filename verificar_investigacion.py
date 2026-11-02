"""Prueba real opcional y aislada: no carga .env, TiDB, usuarios ni credenciales.

python verificar_investigacion.py --live --message "..." [--message "seguimiento"]
Sin --live solo verifica fuentes/índices locales; --web permite fuentes gratuitas.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time


def source_revision(base):
    digest = hashlib.sha256()
    for name in ('literary_ai', 'literary_identity', 'literary_conversation', 'literary_constraints',
                 'literary_search', 'literary_research', 'literary_quality', 'local_llm',
                 'books_google', 'ai_catalog_fallback', 'ai_public_details', 'literary_web',
                 'literary_sources', 'ai_identification_details', 'literary_ai_views',
                 'ai_literal_followup', 'ai_recommendation_provenance'):
        path = base / 'core' / (name + '.py')
        digest.update(name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--web', action='store_true')
    parser.add_argument('--public-catalog', action='store_true',
                        help='Usa APIs bibliográficas reales sin acceder a la base Django.')
    parser.add_argument('--trace', action='store_true', help='Guarda borradores solo en el informe local de esta prueba aislada.')
    parser.add_argument('--model', default='qwen3.5:9b-q4_K_M',
                        help='Modelo local descargado; nunca admite servicios cloud.')
    parser.add_argument('--context', type=int, default=16384,
                        help='Ventana de contexto local para comparar consumo y latencia.')
    parser.add_argument('--message', action='append')
    parser.add_argument('--output', default='reportes/investigacion_real.json')
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    os.environ.pop('DJANGO_SETTINGS_MODULE', None)
    from django.conf import settings
    settings.configure(SECRET_KEY='isolated-local-research', BASE_DIR=base,
        INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes', 'core', 'suscripciones'],
        DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
        CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
        USE_TZ=True, DEFAULT_AUTO_FIELD='django.db.models.BigAutoField',
        LITMATE_USE_GOOGLE_BOOKS_API=False, GOOGLE_BOOKS_API_KEY='',
        LITMATE_AI_USE_OPENLIBRARY=args.web, LITMATE_AI_USE_WEB=args.web,
        LITMATE_AI_USE_SEARXNG=args.web, LITMATE_AI_USE_WIKIDATA=args.web,
        LITMATE_AI_QUALITY_CHECKS=True, LITMATE_AI_REQUIRE_BOOK_SOURCES=True,
        LITMATE_AI_FAST_RECOMMENDATIONS=True, LITMATE_RESEARCH_ENABLED=True,
        LITMATE_LOCAL_MODEL=args.model,
        LITMATE_LOCAL_GUARD_MODEL=args.model,
        LITMATE_LOCAL_CONTEXT=args.context, LITMATE_LOCAL_ANSWER_TOKENS=3072,
        LITMATE_AI_TOTAL_TIMEOUT=360, LITMATE_RAG_SEMANTIC=True)
    import django
    django.setup()
    from core.literary_knowledge import search_knowledge, search_knowledge_semantic
    from core.literary_ai import build_assistant
    from core.literary_identity import work_identity
    from core.literary_search import retrieve_web
    from unittest.mock import patch
    from core.literary_conversation import resolve_topic_context, remember_topic
    messages = args.message or ['Dime los personajes de Papelucho y el marciano', '¿Y qué sucede con Det?']
    report, history = [], []
    conversation_state = {'turns': history}
    initial_revision = source_revision(base)
    output = (base / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    def local_search(query):
        if args.public_catalog:
            from core.literary_search import retrieve_books
            # Únicamente se excluye SQL. Los catálogos públicos y el lector web
            # hacen solicitudes reales a través de la misma capa de la aplicación.
            with patch('core.literary_search.search_catalog', return_value=[]):
                return retrieve_books(query)
        found = search_knowledge(query, maximum=8)
        return found or search_knowledge_semantic(query, maximum=3)
    for message in messages:
        started = time.monotonic()
        if args.live:
            bot, model = build_assistant(settings, search=local_search,
                web_search=retrieve_web if args.web else lambda query: [])
            drafts = []
            if args.trace:
                original_generate = model._generate
                def traced_generate(stage, prompt, data, name):
                    stage_started = time.monotonic()
                    result = original_generate(stage, prompt, data, name)
                    snapshot = {'stage': stage, 'draft': result}
                    if stage in {'answer', 'answer_web', 'repair', 'audit'}:
                        # Solo fuentes públicas/locales autorizadas y sus IDs;
                        # no copia historial ni instrucciones del lector.
                        snapshot['available_sources_for_local_review'] = copy.deepcopy(data.get('sources', []))
                        snapshot['recommendation_evidence_sources'] = copy.deepcopy(
                            data.get('recommendation_evidence_sources', []))
                    drafts.append(snapshot)
                    print(json.dumps({'local_stage': stage,
                        'seconds': round(time.monotonic() - stage_started, 3)}, ensure_ascii=True), flush=True)
                    return result
                model._generate = traced_generate
            from core.ai_public_details import character_answer
            topic_context = resolve_topic_context(message, conversation_state)
            remember_topic(conversation_state, message, topic_context)
            from core.literary_sources import bounded_research, research_snapshot
            @bounded_research
            def answer_turn():
                # Mismo presupuesto compartido que chatbot_query: la ruta
                # rápida no obtiene lecturas adicionales fuera del límite.
                result = character_answer(message, history, local_search,
                    retrieve_web if args.web else lambda query: [])
                if result is None:
                    from core.ai_identification_details import identification_answer
                    result = identification_answer(message)
                if result is None:
                    result = bot.reply(message, history, topic_context=topic_context)
                result.diagnostics['external_research'] = research_snapshot()
                return result
            result = answer_turn()
            item = {'question': message, 'status': result.status, 'answer': result.text,
                    'model': args.model,
                    'diagnostics': result.diagnostics, 'local_model_calls': model.calls,
                    'sources_used': [{key: source.get(key) for key in
                        ('title', 'url', 'kind', 'source', 'read_mode', 'extraction_method')}
                        for source in result.sources]}
            if result.remember:
                lookup = {source['id']: source for source in result.sources}
                books = [{**book, **work_identity(lookup.get(book['source_id'], book)),
                          'source': lookup.get(book['source_id'], {}).get('source', ''),
                          'url': lookup.get(book['source_id'], {}).get('url', '')} for book in result.books]
                history.append({'accepted': True, 'question': message, 'answer': result.text,
                                'books': books, 'sources': result.sources})
            if args.trace:
                item['verified_sources_for_local_review'] = result.sources
        else:
            sources = retrieve_web(message) if args.web else local_search(message)
            item = {'question': message, 'sources': [{'title': s['title'], 'kind': s['kind'],
                                                     'url': s.get('url', ''), 'read_mode': s.get('read_mode', ''),
                                                     'characters': len(s.get('description', ''))} for s in sources],
                    'retrieval_status': getattr(sources, 'status', 'ok')}
        item['seconds'] = round(time.monotonic() - started, 3)
        item['configuration'] = {'model': args.model, 'context': args.context,
                                 'public_catalog': args.public_catalog, 'web': args.web}
        item['source_revision'] = initial_revision
        item['source_files_changed_during_run'] = source_revision(base) != initial_revision
        report.append(item)
        print(json.dumps(item, ensure_ascii=True), flush=True)
        if args.live and args.trace:
            item['drafts_for_local_review'] = drafts
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 1 if any(item.get('status') == 'unavailable' for item in report) else 0


if __name__ == '__main__':
    raise SystemExit(main())
