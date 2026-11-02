"""Real HTTP/SSE checks against the selected MySQL DEFAULT database.

Uses the production URLconf, middleware, templates, providers and DB sessions.
Creates an ordinary anonymous chat session; never impersonates a user or deletes
data to restore a test count. Reports contain no cookies or imported private text.
"""
from datetime import datetime, timezone
from http.cookiejar import CookieJar
import hashlib
import json
from pathlib import Path
from socketserver import ThreadingMixIn
import threading
import time
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request
from urllib.error import HTTPError
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server


def file_digest(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def verify_activation():
    from django.conf import settings
    from django.core.handlers.wsgi import WSGIHandler
    from django.db import connection, close_old_connections
    from django.contrib.auth.models import User
    from django.contrib.sessions.models import Session
    from .models import Libro, ConversacionIA, MensajeIA
    from .literary_ai_views import HISTORY_KEY
    from .database_transfer import (verify_backup, check_schema, inspect_table, table_rows,
                                    fingerprint, fresh_mysql_metadata, next_id_value)
    root = Path(settings.BASE_DIR)
    reports = root / 'reportes' / 'mysql_activacion_20261028'
    reports.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    report_path = reports / ('activacion_' + stamp + '.json')
    env_before = file_digest(root / '.env')
    backup = root / 'backups' / 'mysql_preparacion_20261028_03'
    manifest = verify_backup(backup)
    # A running application's data legitimately evolves after import. Snapshot
    # current rows; never demand that sessions/new user activity match an old backup.
    check_schema(connection, manifest['database'])
    connection.check_constraints()
    fresh_mysql_metadata(connection)
    baseline = {}
    for name, imported in manifest['database']['tables'].items():
        columns, pk, _ = inspect_table(connection, name)
        rows = table_rows(connection, name)
        current = fingerprint(name, columns, rows, pk)
        if imported.get('next_id'):
            maximum = max((r[columns.index(pk)] for r in rows), default=0)
            current['next_id'] = next_id_value(connection, name)
            if current['next_id'] <= maximum:
                raise RuntimeError('El próximo ID no supera el mayor ID de la tabla.')
        baseline[name] = current
    report = {'mode': 'real_default_mysql_http_sse', 'report': str(report_path), 'passed': False,
        'engine': settings.DATABASES['default']['ENGINE'], 'database': settings.DATABASES['default']['NAME'],
        'driver': connection.connection.__class__.__module__, 'session_engine': settings.SESSION_ENGINE,
        'baseline_integrity_verified': True, 'tables_before': baseline,
        'baseline_kind': 'current_runtime_snapshot_not_an_import_or_reset',
        'env_sha256_before': env_before, 'pages': [], 'conversation': [], 'limitations': [
            'Authenticated history is read via ORM; no private account was impersonated.',
            'Anonymous chat persists in MySQL django_session, not ConversacionIA/MensajeIA.']}
    # Actually materialize foreign-key joins without logging private content.
    sample_book = Libro.objects.select_related('autor', 'editorial').first()
    sample_message = MensajeIA.objects.select_related('conversacion__usuario').first()
    report['orm'] = {'users': User.objects.count(), 'books': Libro.objects.count(),
        'conversations': ConversacionIA.objects.count(), 'messages': MensajeIA.objects.count(),
        'book_author_join': bool(sample_book and sample_book.autor_id and sample_book.autor.nombre),
        'imported_history_join': bool(sample_message and sample_message.conversacion.usuario_id
                                      and sample_message.contenido)}
    from .literary_memory import coverage_snapshot, retrieve_evidence
    coverage = coverage_snapshot()
    books, sources = retrieve_evidence('El principito', limit=6)
    report['persistent_knowledge'] = {'backend': 'independent SQLite', 'coverage': coverage,
                                    'sample_books': len(books), 'sample_sources': len(sources)}
    report['auxiliary_stores'] = {key: {'path': str(getattr(settings, key)),
        'exists': Path(getattr(settings, key)).is_file()} for key in dir(settings)
        if key.startswith('LITMATE_') and key.endswith('_DB')}

    class Server(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args):
            pass

    try:
        with make_server('127.0.0.1', 0, WSGIHandler(), server_class=Server, handler_class=QuietHandler) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            origin = 'http://127.0.0.1:' + str(server.server_port)
            cookies = CookieJar()
            client = build_opener(ProxyHandler({}), HTTPCookieProcessor(cookies))
            try:
                for path in ('/', '/chat/', '/libros/'):
                    started = time.monotonic()
                    with client.open(origin + path, timeout=45) as response:
                        html = response.read()
                        report['pages'].append({'path': path, 'status': response.status,
                            'html_bytes': len(html), 'seconds': round(time.monotonic() - started, 3)})
                csrf = next(cookie.value for cookie in cookies if cookie.name == settings.CSRF_COOKIE_NAME)
                bad = Request(origin + '/chatbot_query/', data=b'{"message":"Hola"}',
                    headers={'Content-Type': 'application/json', 'Origin': origin}, method='POST')
                try:
                    with client.open(bad, timeout=10) as response:
                        report['csrf_without_token_status'] = response.status
                except HTTPError as error:
                    report['csrf_without_token_status'] = error.code
                for message in ('¿De qué trata El principito?', '¿Y sus personajes?', '¿Quién escribió ese libro?'):
                    started, phases, text, ready, done = time.monotonic(), [], '', None, False
                    req = Request(origin + '/chatbot_query/', data=json.dumps({'message': message,
                        'progress': True}).encode(), headers={'Content-Type': 'application/json',
                        'X-CSRFToken': csrf, 'Origin': origin}, method='POST')
                    with client.open(req, timeout=100) as response:
                        for line in response:
                            if not line.startswith(b'data: '):
                                continue
                            event = line[6:].decode('utf-8').strip()
                            if event == '[DONE]':
                                done = True
                                break
                            payload = json.loads(event)
                            text += payload.get('token', '')
                            if payload.get('stage'):
                                phases.append(payload['stage'])
                            if payload.get('ready'):
                                ready = payload['ready']
                    if not ready:
                        raise RuntimeError('SSE no entregó una respuesta finalizable.')
                    req = Request(origin + '/chatbot_finalize/', data=json.dumps({'ready': ready}).encode(),
                        headers={'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'Origin': origin}, method='POST')
                    with client.open(req, timeout=30) as response:
                        payload = json.load(response)
                        diagnostics = payload.get('diagnostics', {})
                        report['conversation'].append({'question': message, 'status': payload.get('status'),
                            'http_status': response.status, 'answer': payload.get('response', ''),
                            'seconds': round(time.monotonic() - started, 3), 'sse_done': done,
                            'phases': phases, 'cards': len(payload.get('books', [])),
                            'model_calls': diagnostics.get('model_calls')})
                # Look up only this client session, never publish its cookie/key.
                key = next(cookie.value for cookie in cookies if cookie.name == settings.SESSION_COOKIE_NAME)
                close_old_connections()
                row = Session.objects.get(pk=key)
                state = row.get_decoded().get(HISTORY_KEY, {})
                report['mysql_chat_session'] = {'found': True, 'accepted_turns': len(state.get('turns', [])),
                    'active_title': (state.get('active_work') or {}).get('title', '')}
                after, deltas = {}, {}
                for table, previous in baseline.items():
                    columns, pk, _ = inspect_table(connection, table)
                    current = fingerprint(table, columns, table_rows(connection, table), pk)
                    after[table] = current
                    deltas[table] = current['count'] - previous['count']
                    if table not in {'django_session', 'django_migrations'}:
                        if any(current[k] != previous[k] for k in current):
                            raise RuntimeError('La comprobación alteró una tabla de datos inesperada.')
                connection.check_constraints()
                report['row_deltas'] = {k: v for k, v in deltas.items() if v}
                report['rows_after'] = sum(t['count'] for t in after.values())
                report['passed'] = (all(t['status'] == 'answered' for t in report['conversation'])
                    and report['csrf_without_token_status'] == 403
                    and report['mysql_chat_session']['accepted_turns'] == 3
                    and report['orm']['book_author_join'] and report['orm']['imported_history_join'])
            finally:
                server.shutdown()
                worker.join(timeout=5)
    except HTTPError as error:
        # Extract only known reason codes; never persist a debug HTML page.
        body = error.read().decode('utf-8', 'replace')
        reasons = ['Origin checking failed', 'CSRF cookie not set', 'CSRF token missing',
                   'incorrect', 'Referer checking failed', 'CSRF cookie has incorrect length']
        report['csrf_failure_markers'] = [s for s in reasons if s in body]
        report['cookie_properties'] = [{'name': c.name, 'secure': c.secure, 'path': c.path}
                                       for c in cookies]
        report['error_class'], report['error_code'] = type(error).__name__, error.code
    except Exception as error:
        # Do not save HTML debug pages, settings, headers, session keys or user data.
        report['error_class'] = type(error).__name__
        report['error_code'] = getattr(error, 'code', None)
    report['env_sha256_after'] = file_digest(root / '.env')
    report['env_unchanged'] = report['env_sha256_before'] == report['env_sha256_after']
    report['backup_manifest_sha256'] = file_digest(backup / 'manifest.json')
    report['passed'] = report['passed'] and report['env_unchanged']
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
