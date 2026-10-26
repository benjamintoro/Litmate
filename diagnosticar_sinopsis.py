"""Traza recuperación y síntesis optativa con almacenes aislados, sin migraciones."""
import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--message', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--synthesize', action='store_true', help='Ejecuta generación/auditoría reales y conserva su traza local.')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('El informe ya existe; usa otra ruta.')
    base = Path(__file__).resolve().parent
    temporary_root = base / '.test-tmp'
    temporary_root.mkdir(exist_ok=True)
    os.environ.pop('DJANGO_SETTINGS_MODULE', None)
    from django.conf import settings
    with TemporaryDirectory(prefix='narrative-retrieval-', dir=temporary_root) as temporary:
        root = Path(temporary)
        settings.configure(BASE_DIR=base, SECRET_KEY='isolated-retrieval-only', USE_TZ=True,
            DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
            INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes', 'core', 'suscripciones'],
            CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
            LITMATE_AI_USE_WEB=True, LITMATE_AI_USE_OPENLIBRARY=True, LITMATE_AI_USE_SEARXNG=True,
            LITMATE_USE_GOOGLE_BOOKS_API=False, GOOGLE_BOOKS_API_KEY='',
            LITMATE_KNOWLEDGE_DB=root / 'knowledge.sqlite3', LITMATE_RAG_DB=root / 'rag.sqlite3',
            LITMATE_KNOWLEDGE_RAG_DB=root / 'knowledge-rag.sqlite3',
            LITMATE_LITERARY_MEMORY_DB=root / 'memory.sqlite3',
            LITMATE_LITERARY_MEMORY_RAG_DB=root / 'memory-rag.sqlite3')
        import django
        django.setup()
        from core.ai_budget import request_budget
        from core.ai_progress import progress_scope, snapshot_metrics
        from core.literary_sources import research_scope, research_snapshot
        from core.ai_narrative_answers import request_for, retrieve_sources, synthesize_answer, _content
        settings.LITMATE_LOCAL_MODEL = 'qwen3.5:9b-q4_K_M'
        settings.LITMATE_LOCAL_GUARD_MODEL = settings.LITMATE_LOCAL_MODEL
        report = {'mode': 'real_retrieval_and_local_synthesis' if args.synthesize else
                  'real_retrieval_no_llm_temporary_databases', 'queries': []}
        for message in args.message:
            start = time.monotonic()
            with request_budget(start + (36 if args.synthesize else 22)), research_scope(), progress_scope():
                request = request_for(message)
                try:
                    sources = retrieve_sources(message, request, []) if request else []
                    row = {'question': message, 'request': request, 'sources': sources,
                           'content_sources': sum(bool(_content(source)) for source in sources),
                           'research': research_snapshot(), 'metrics': snapshot_metrics()}
                    if args.synthesize and any(_content(source) for source in sources):
                        stages = []
                        result, client = synthesize_answer(message, request, sources, settings,
                            trace=lambda stage, value: stages.append({'stage': stage, 'output': value}))
                        row.update(status=result.status, answer=result.text, diagnostics=result.diagnostics,
                                   model_calls=client.calls, stages=stages, metrics=snapshot_metrics())
                except Exception as error:
                    row = {'question': message, 'request': request, 'error': type(error).__name__}
                row['seconds'] = round(time.monotonic() - start, 3)
                report['queries'].append(row)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps({key: row.get(key) for key in ('question', 'seconds', 'content_sources', 'error')}, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
