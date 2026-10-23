"""Benchmark HTTP/SSE real, aislado y sin .env, migraciones ni datos de usuario.

Usa el endpoint de producción en un servidor loopback efímero. Crea tablas
vacías con schema_editor SOLO dentro de TemporaryDirectory; Ollama y las
fuentes públicas son reales. No sustituye búsquedas ni inferencia con mocks.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from http.cookiejar import CookieJar
import json
import hashlib
import math
import os
from pathlib import Path
import re
import statistics
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server


urlpatterns = []


def code_revision(base):
    digest = hashlib.sha256()
    for name in ('ai_budget.py', 'ai_quick_answers.py', 'literary_language.py',
                 'literary_ai.py', 'literary_ai_views.py', 'literary_search.py',
                  'literary_quality.py', 'literary_research.py', 'literary_conversation.py', 'literary_constraints.py',
                  'literary_web.py', 'literary_sources.py', 'ai_presentation.py',
                 'books_google.py', 'local_llm.py', 'literary_identity.py', 'literary_evidence.py',
                 'ai_identification_details.py', 'ai_public_details.py', 'topic_reference.py',
                 'data/topic_reference.json', 'data/verified_readings.json'):
        digest.update((base / 'core' / name).read_bytes())
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--matrix', type=Path)
    parser.add_argument('--case', action='append', default=[])
    parser.add_argument('--message', action='append', default=[])
    parser.add_argument('--model', default='qwen3.5:9b-q4_K_M')
    parser.add_argument('--chat-budget', type=float, default=36,
                        help='Segundos de trabajo literario antes de cerrar el stream.')
    parser.add_argument('--response-budget', type=float, default=42,
                        help='Segundos máximos que espera el cliente HTTP.')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--no-web', action='store_true')
    args = parser.parse_args(argv)
    if args.chat_budget <= 0 or args.response_budget <= args.chat_budget:
        parser.error('--response-budget debe ser mayor que --chat-budget.')
    if args.output.exists():
        parser.error('El informe ya existe; usa otra ruta para no sobrescribirlo.')
    cases = []
    if args.matrix:
        matrix = json.loads(args.matrix.read_text(encoding='utf-8-sig'))
        cases = [case for case in matrix['cases'] if case['mode'] == 'live'
                 and (not args.case or case['id'] in args.case)]
    if args.message:
        cases.append({'id': 'consulta_reportada', 'messages': [{'text': message} for message in args.message]})
    if not cases:
        parser.error('Indica --matrix o al menos un --message.')
    base = Path(__file__).resolve().parent
    temporary_root = base / '.test-tmp'
    temporary_root.mkdir(exist_ok=True)
    os.environ.pop('DJANGO_SETTINGS_MODULE', None)
    with tempfile.TemporaryDirectory(prefix='chat-http-', dir=temporary_root) as temporary:
        root = Path(temporary)
        from django.conf import settings
        settings.configure(SECRET_KEY='isolated-http-literary-benchmark-' + 'x' * 40,
            BASE_DIR=base, DEBUG=False, ALLOWED_HOSTS=['127.0.0.1'], ROOT_URLCONF=__name__,
            INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes',
                            'django.contrib.sessions', 'core', 'suscripciones'],
            DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(root / 'empty.sqlite3')}},
            MIDDLEWARE=['django.contrib.sessions.middleware.SessionMiddleware',
                        'django.middleware.csrf.CsrfViewMiddleware',
                        'django.contrib.auth.middleware.AuthenticationMiddleware'],
            CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': temporary}},
            SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies',
            USE_TZ=True, DEFAULT_AUTO_FIELD='django.db.models.BigAutoField',
            LITMATE_AI_LOCK_BACKEND='sqlite', LITMATE_AI_RUNTIME_DB=root / 'runtime.sqlite3',
            LITMATE_USE_EXISTING_QUOTAS=False, LITMATE_AI_REQUESTS_PER_MINUTE=1000,
            LITMATE_USE_GOOGLE_BOOKS_API=False, GOOGLE_BOOKS_API_KEY='',
            LITMATE_LOCAL_MODEL=args.model, LITMATE_LOCAL_GUARD_MODEL=args.model,
            LITMATE_AI_TOTAL_TIMEOUT=360, LITMATE_CHAT_TIMEOUT=args.chat_budget,
            LITMATE_LOCAL_CONTEXT=16384, LITMATE_LOCAL_ANSWER_TOKENS=3072,
            LITMATE_AI_USE_WEB=not args.no_web, LITMATE_AI_USE_SEARXNG=not args.no_web,
            LITMATE_AI_USE_OPENLIBRARY=not args.no_web, LITMATE_RAG_SEMANTIC=True)
        import django
        django.setup()
        from django.apps import apps
        from django.db import connection, connections
        with connection.schema_editor() as editor:
            for model in apps.get_models():
                editor.create_model(model)
        from django.core.handlers.wsgi import WSGIHandler
        from django.http import HttpResponse
        from django.urls import path
        from django.views.decorators.csrf import ensure_csrf_cookie
        from core.literary_ai_views import chatbot_query
        urlpatterns.extend([path('csrf/', ensure_csrf_cookie(lambda request: HttpResponse('ready'))),
                            path('chatbot_query/', chatbot_query)])

        class Server(ThreadingMixIn, WSGIServer):
            daemon_threads = True

        class QuietHandler(WSGIRequestHandler):
            def log_message(self, *args):
                pass

        with make_server('127.0.0.1', 0, WSGIHandler(), server_class=Server, handler_class=QuietHandler) as server:
            serving = threading.Thread(target=server.serve_forever, daemon=True)
            serving.start()
            origin = f'http://127.0.0.1:{server.server_port}'
            report = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
                      'mode': 'real_http_sse_isolated_database', 'model': args.model,
                      'web_enabled': not args.no_web, 'chat_budget_seconds': args.chat_budget,
                      'response_budget_seconds': args.response_budget,
                      'factual_review': 'not_independently_certified', 'turns': []}
            report['source_sha256'] = code_revision(base)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            try:
                for case in cases:
                    cookies = CookieJar()
                    client = build_opener(ProxyHandler({}), HTTPCookieProcessor(cookies))
                    with client.open(origin + '/csrf/', timeout=2) as response:
                        response.read()
                    csrf = next(cookie.value for cookie in cookies if cookie.name == 'csrftoken')
                    for index, item in enumerate(case['messages'], 1):
                        message = item['text']
                        request = Request(origin + '/chatbot_query/',
                            data=json.dumps({'message': message}).encode('utf-8'),
                            headers={'Content-Type': 'application/json', 'X-CSRFToken': csrf}, method='POST')
                        start, first_useful, done, text = time.monotonic(), None, False, ''
                        try:
                            with client.open(request, timeout=args.response_budget) as response:
                                status = response.headers.get('X-LitMate-Status', 'unknown')
                                calls = response.headers.get('X-LitMate-Model-Calls')
                                http_status = response.status
                                for raw in response:
                                    if not raw.startswith(b'data: '):
                                        continue
                                    event = raw[6:].decode('utf-8').strip()
                                    if event == '[DONE]':
                                        done = True
                                        break
                                    payload = json.loads(event)
                                    token = payload.get('token', '')
                                    if token and first_useful is None:
                                        first_useful = time.monotonic() - start
                                    text += token
                        except HTTPError as exc:
                            http_status, status, calls = exc.code, 'http_error', None
                            text = exc.read(4000).decode('utf-8', 'replace')
                        except Exception as exc:
                            http_status, status, calls = None, type(exc).__name__, None
                        elapsed = time.monotonic() - start
                        row = {'case': case['id'], 'turn': index, 'question': message,
                            'http_status': http_status, 'status': status, 'completed_sse': done,
                            'seconds': round(elapsed, 3),
                            'first_text_seconds': round(first_useful, 3) if first_useful is not None else None,
                            'first_useful_seconds': round(first_useful, 3)
                                if first_useful is not None and status == 'answered' else None,
                            'under_response_budget': elapsed <= args.response_budget,
                            'model_calls': int(calls) if calls else None,
                            'answer': text, 'source_urls': re.findall(r'https://\S+', text)}
                        report['turns'].append(row)
                        samples = [turn['seconds'] for turn in report['turns']]
                        ordered = sorted(samples)
                        report['metrics'] = {'turns': len(samples), 'p50_seconds': statistics.median(samples),
                            'p95_seconds': ordered[max(0, math.ceil(len(samples) * .95) - 1)],
                            'max_seconds': max(samples),
                            'under_response_budget': sum(turn['under_response_budget'] for turn in report['turns']),
                            'statuses': dict(Counter(turn['status'] for turn in report['turns']))}
                        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                        print(json.dumps({key: row[key] for key in ('case', 'turn', 'status', 'seconds', 'under_response_budget')},
                                         ensure_ascii=True), flush=True)
            finally:
                server.shutdown()
                serving.join(timeout=2)
                connections.close_all()
            report['source_files_changed_during_run'] = code_revision(base) != report['source_sha256']
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report['metrics']), flush=True)
    return int(any(not row['under_response_budget'] or not row['completed_sse'] for row in report['turns']))


if __name__ == '__main__':
    raise SystemExit(main())
