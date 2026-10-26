"""Benchmark HTTP/SSE real, aislado y sin .env, migraciones ni datos de usuario.

Usa el endpoint de producción en un servidor loopback efímero. Crea tablas
vacías con schema_editor SOLO dentro de TemporaryDirectory; Ollama y las
fuentes públicas son reales. No sustituye búsquedas ni inferencia con mocks.
"""
import argparse
import copy
from collections import Counter
from datetime import datetime, timezone
from http.cookiejar import CookieJar
import io
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
    files = [path for path in (base / 'core').rglob('*.py') if not path.name.startswith('test')]
    files += [base / 'core' / 'data' / name for name in ('topic_reference.json', 'verified_readings.json')]
    for path in sorted(files):
        digest.update(str(path.relative_to(base)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def memory_snapshot():
    """RSS/peak del proceso servidor; no equivale al consumo de Ollama/GPU."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ('peak', 'working', 'peak_paged', 'paged',
                    'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile')]
        value = Counters()
        value.cb = ctypes.sizeof(value)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        read_memory = ctypes.WinDLL('psapi').GetProcessMemoryInfo
        read_memory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        read_memory.restype = wintypes.BOOL
        if read_memory(kernel.GetCurrentProcess(), ctypes.byref(value), value.cb):
            return {'rss_mb': round(value.working / 2**20, 3), 'peak_rss_mb': round(value.peak / 2**20, 3)}
    return {}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--matrix', type=Path)
    parser.add_argument('--case', action='append', default=[])
    parser.add_argument('--message', action='append', default=[])
    parser.add_argument('--model', default='qwen3.5:9b-q4_K_M')
    parser.add_argument('--context', type=int, default=16384)
    parser.add_argument('--prewarm', action='store_true',
                        help='Precarga el modelo instalado con prompt vacío, sin preparar respuestas.')
    parser.add_argument('--trace-narrative', action='store_true',
                        help='Guarda borrador/auditoría narrativa únicamente en el informe local aislado.')
    parser.add_argument('--chat-budget', type=float, default=36,
                        help='Segundos de trabajo literario antes de cerrar el stream.')
    parser.add_argument('--response-budget', type=float, default=42,
                        help='Segundos máximos que espera el cliente HTTP.')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--no-web', action='store_true')
    parser.add_argument('--progressive', action='store_true', help='Mide SSE temprano + POST de finalización real.')
    parser.add_argument('--repeat', type=int, default=1, help='Repite cada turno en su conversación, sin preparar respuestas.')
    parser.add_argument('--empty-answer-cache-each-turn', action='store_true')
    parser.add_argument('--empty-retrieval-cache-each-turn', action='store_true')
    args = parser.parse_args(argv)
    if args.chat_budget <= 0 or args.response_budget <= args.chat_budget:
        parser.error('--response-budget debe ser mayor que --chat-budget.')
    if not 1 <= args.repeat <= 20:
        parser.error('--repeat debe estar entre 1 y 20.')
    if not 8192 <= args.context <= 32768:
        parser.error('--context debe estar entre 8192 y 32768.')
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
            LITMATE_AI_STREAM_DB=root / 'stream.sqlite3',
            LITMATE_AI_ANSWER_CACHE_DB=root / 'answers.sqlite3',
            LITMATE_LITERARY_MEMORY_DB=root / 'memory.sqlite3',
            LITMATE_LITERARY_MEMORY_RAG_DB=root / 'memory-rag.sqlite3',
            LITMATE_KNOWLEDGE_DB=root / 'knowledge.sqlite3',
            LITMATE_KNOWLEDGE_RAG_DB=root / 'knowledge-rag.sqlite3',
            LITMATE_RAG_DB=root / 'rag.sqlite3',
            LITMATE_USE_EXISTING_QUOTAS=False, LITMATE_AI_REQUESTS_PER_MINUTE=1000,
            LITMATE_USE_GOOGLE_BOOKS_API=False, GOOGLE_BOOKS_API_KEY='',
            LITMATE_LOCAL_MODEL=args.model, LITMATE_LOCAL_GUARD_MODEL=args.model,
            LITMATE_AI_TOTAL_TIMEOUT=360, LITMATE_CHAT_TIMEOUT=args.chat_budget,
            LITMATE_LOCAL_CONTEXT=args.context, LITMATE_LOCAL_ANSWER_TOKENS=3072,
            LITMATE_AI_USE_WEB=not args.no_web, LITMATE_AI_USE_SEARXNG=not args.no_web,
            LITMATE_AI_USE_OPENLIBRARY=not args.no_web,
            LITMATE_AI_USE_WIKIDATA=not args.no_web, LITMATE_RAG_SEMANTIC=True)
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
        from core.literary_ai_views import chatbot_query, chatbot_finalize
        narrative_traces = []
        if args.trace_narrative:
            from core import ai_narrative_answers
            original_synthesis = ai_narrative_answers.synthesize_answer
            def traced_synthesis(message, request, sources, config, **kwargs):
                row = {'question': message, 'request': copy.deepcopy(request),
                       'sources': copy.deepcopy(sources), 'stages': []}
                kwargs['trace'] = lambda stage, value: row['stages'].append(
                    {'stage': stage, 'output': copy.deepcopy(value)})
                result, client = original_synthesis(message, request, sources, config, **kwargs)
                row.update(status=result.status, diagnostics=copy.deepcopy(result.diagnostics))
                narrative_traces.append(row)
                return result, client
            ai_narrative_answers.synthesize_answer = traced_synthesis
        urlpatterns.extend([path('csrf/', ensure_csrf_cookie(lambda request: HttpResponse('ready'))),
                            path('chatbot_query/', chatbot_query), path('chatbot_finalize/', chatbot_finalize)])
        warmup = {'requested': args.prewarm, 'seconds': None, 'generates_answers': False}
        if args.prewarm:
            from django.core.management import call_command
            started = time.monotonic()
            # Reutiliza la comprobación GGUF/local del comando existente; no
            # hace pull ni genera respuestas de ninguna pregunta de la matriz.
            call_command('precalentar_ia', keep_alive='10m', timeout=180, stdout=io.StringIO())
            warmup['seconds'] = round(time.monotonic() - started, 3)

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
                       'context': args.context, 'prewarm': warmup,
                       'web_enabled': not args.no_web, 'chat_budget_seconds': args.chat_budget,
                       'response_budget_seconds': args.response_budget,
                      'progressive': args.progressive, 'repeat': args.repeat,
                      'knowledge_setup': 'empty_auxiliary_databases_with_bundled_catalogue',
                      'resource_scope': 'python_server_process_only_not_ollama_or_gpu',
                      'cache_controls': {'empty_answers_each_turn': args.empty_answer_cache_each_turn,
                                         'empty_retrieval_each_turn': args.empty_retrieval_cache_each_turn},
                      'factual_review': 'not_independently_certified', 'turns': []}
            if args.trace_narrative:
                report['narrative_traces'] = narrative_traces
            report['source_sha256'] = code_revision(base)
            report['runner_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            report['matrix_sha256'] = hashlib.sha256(args.matrix.read_bytes()).hexdigest() if args.matrix else None
            args.output.parent.mkdir(parents=True, exist_ok=True)
            try:
                for case in cases:
                    cookies = CookieJar()
                    client = build_opener(ProxyHandler({}), HTTPCookieProcessor(cookies))
                    with client.open(origin + '/csrf/', timeout=2) as response:
                        response.read()
                    csrf = next(cookie.value for cookie in cookies if cookie.name == 'csrftoken')
                    messages = [item for item in case['messages'] for _ in range(args.repeat)]
                    for index, item in enumerate(messages, 1):
                        if args.empty_answer_cache_each_turn:
                            from core.ai_answer_cache import delete_owner_cache
                            delete_owner_cache()
                        if args.empty_retrieval_cache_each_turn:
                            from django.core.cache import cache
                            cache.clear()  # Únicamente caché de este servidor temporal.
                        message = item['text']
                        request = Request(origin + '/chatbot_query/',
                            data=json.dumps({'message': message, 'progress': args.progressive}).encode('utf-8'),
                            headers={'Content-Type': 'application/json', 'X-CSRFToken': csrf}, method='POST')
                        cpu_start = time.process_time()
                        start, first_useful, first_phase, done, text = time.monotonic(), None, None, False, ''
                        phases, diagnostics = [], {}
                        ready = None
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
                                    if payload.get('stage'):
                                        if first_phase is None:
                                            first_phase = time.monotonic() - start
                                        phases.append(payload['stage'])
                                    if payload.get('ready'):
                                        ready = payload['ready']
                                    token = payload.get('token', '')
                                    if token and first_useful is None:
                                        first_useful = time.monotonic() - start
                                    text += token
                            if ready:
                                finalize = Request(origin + '/chatbot_finalize/',
                                    data=json.dumps({'ready': ready}).encode(),
                                    headers={'Content-Type': 'application/json', 'X-CSRFToken': csrf}, method='POST')
                                with client.open(finalize, timeout=max(.1, args.response_budget - (time.monotonic() - start))) as response:
                                    body = json.load(response)
                                    status, text = body['status'], body['response']
                                    diagnostics = body.get('diagnostics', {})
                                    calls = diagnostics.get('model_calls')
                                    first_useful = time.monotonic() - start
                        except HTTPError as exc:
                            http_status, status, calls = exc.code, 'http_error', None
                            text = exc.read(4000).decode('utf-8', 'replace')
                        except Exception as exc:
                            http_status, status, calls = None, type(exc).__name__, None
                        elapsed = time.monotonic() - start
                        progress = (diagnostics.get('progress_metrics')
                                    if isinstance(diagnostics, dict) else None)
                        work_ms = progress.get('elapsed_ms') if isinstance(progress, dict) else None
                        delivery_ms = (round(max(0., elapsed * 1000 - work_ms), 3)
                                       if type(work_ms) in {int, float} and work_ms >= 0 else None)
                        row = {'case': case['id'], 'turn': index, 'question': message,
                            'http_status': http_status, 'status': status, 'completed_sse': done,
                            'seconds': round(elapsed, 3),
                            'first_text_seconds': round(first_useful, 3) if first_useful is not None else None,
                            'first_useful_seconds': round(first_useful, 3)
                                if first_useful is not None and status == 'answered' else None,
                            'first_progress_seconds': round(first_phase, 3) if first_phase is not None else None,
                            'progress_phases': phases, 'diagnostics': diagnostics,
                            'stage_totals_ms': (progress.get('stage_totals_ms', {})
                                                if isinstance(progress, dict) else {}),
                            'delivery_overhead_ms': delivery_ms,
                            'resources': {**memory_snapshot(),
                                          'cpu_seconds': round(time.process_time() - cpu_start, 6)},
                            'category': case.get('category', 'unspecified'),
                            'under_response_budget': elapsed <= args.response_budget,
                            'model_calls': int(calls) if calls is not None else None,
                            'answer': text, 'source_urls': re.findall(r'https://\S+', text)}
                        report['turns'].append(row)
                        samples = [turn['seconds'] for turn in report['turns']]
                        ordered = sorted(samples)
                        report['metrics'] = {'turns': len(samples), 'p50_seconds': statistics.median(samples),
                            'mean_seconds': round(statistics.mean(samples), 3),
                            'p95_seconds': ordered[max(0, math.ceil(len(samples) * .95) - 1)],
                            'max_seconds': max(samples),
                            'under_response_budget': sum(turn['under_response_budget'] for turn in report['turns']),
                            'statuses': dict(Counter(turn['status'] for turn in report['turns'])),
                            'under_5_seconds': sum(t['seconds'] < 5 for t in report['turns']),
                            'under_10_seconds': sum(t['seconds'] < 10 for t in report['turns']),
                            'under_30_seconds': sum(t['seconds'] < 30 for t in report['turns']),
                            'answered_is_not_factual_certification': True}
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
