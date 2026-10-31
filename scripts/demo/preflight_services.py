"""Diagnóstico acotado de servicios y check --deploy; no configura Funnel ni redes."""
import argparse
from contextlib import closing
import getpass
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--carpeta', type=Path, required=True)
    parser.add_argument('--host', required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Usa una salida nueva.')
    from iniciar_mysql_local import local_database_environment
    password = getpass.getpass('Contraseña MySQL local (oculta): ')
    with local_database_environment(password):
        password = None
        os.environ.update(DJANGO_SETTINGS_MODULE='litmate_project.demo_settings', DEBUG='False',
            SECRET_KEY=secrets.token_urlsafe(64), LITMATE_DEMO_MODE='https',
            LITMATE_DEMO_HOST=args.host, LITMATE_DEMO_WORKSPACE=str(args.carpeta.resolve()))
        import django
        django.setup()
        from django.conf import settings
        from django.core.management import call_command
        from django.core.checks import run_checks
        from django.db import connection
        from django.test import override_settings
        from iniciar_demo import prepare_workspace
        folder, stores = prepare_workspace(args.carpeta, settings)
        report = {'external_publication_activated': False, 'network_changed': False}
        with override_settings(**stores):
            with connection.cursor() as cursor:
                cursor.execute('SET SESSION TRANSACTION READ ONLY')
                cursor.execute('SELECT DATABASE(), @@session.transaction_read_only, @@GLOBAL.bind_address, @@port')
                name, read_only, address, port = cursor.fetchone()
                cursor.execute('SHOW GLOBAL VARIABLES LIKE %s', ['mysqlx_bind_address'])
                mysqlx = cursor.fetchone()
                cursor.execute('SELECT COUNT(*) FROM core_libro')
                count = cursor.fetchone()[0]
            report['mysql'] = {'database': name, 'session_read_only': bool(read_only), 'bind_address': address,
                               'port': port, 'mysqlx_bind_address': mysqlx[1] if mysqlx else None, 'books': count}
            out, errors = StringIO(), StringIO()
            call_command('check', deploy=True, databases=['default'], stdout=out, stderr=errors)
            report['deploy_check'] = {'output': out.getvalue(), 'warnings_output': errors.getvalue(),
                'checks': [{'id': item.id, 'message': item.msg, 'level': item.level}
                           for item in run_checks(include_deployment_checks=True, databases=['default'])]}
            report['settings'] = {'DEBUG': settings.DEBUG, 'ALLOWED_HOSTS': settings.ALLOWED_HOSTS,
                'CSRF_TRUSTED_ORIGINS': settings.CSRF_TRUSTED_ORIGINS,
                'SESSION_COOKIE_SECURE': settings.SESSION_COOKIE_SECURE,
                'CSRF_COOKIE_SECURE': settings.CSRF_COOKIE_SECURE,
                'SESSION_COOKIE_HTTPONLY': settings.SESSION_COOKIE_HTTPONLY,
                'SESSION_COOKIE_SAMESITE': settings.SESSION_COOKIE_SAMESITE,
                'SESSION_ENGINE': settings.SESSION_ENGINE, 'SECURE_PROXY_SSL_HEADER': settings.SECURE_PROXY_SSL_HEADER,
                'SECURE_SSL_REDIRECT': settings.SECURE_SSL_REDIRECT}
            index = Path(settings.LITMATE_LITERARY_MEMORY_RAG_DB)
            with closing(sqlite3.connect(index.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                report['rag'] = {'quick_check': db.execute('PRAGMA quick_check').fetchone()[0],
                    'documents': db.execute('SELECT COUNT(*) FROM documents').fetchone()[0],
                    'chunks': db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0],
                    'keyword_matches': db.execute('SELECT COUNT(*) FROM chunks WHERE chunks MATCH ?',
                                                 ['principito OR amistad']).fetchone()[0]}
            opener = build_opener(ProxyHandler({}))
            def http(url, data=None, timeout=12):
                started = time.monotonic()
                request = Request(url, data=json.dumps(data).encode() if data else None,
                                  headers={'Content-Type': 'application/json', 'User-Agent': 'LitMate-local-preflight/1'})
                try:
                    with opener.open(request, timeout=timeout) as response:
                        value = json.load(response)
                    return value, {'status': 'ok', 'seconds': round(time.monotonic() - started, 4)}
                except Exception as error:
                    return {}, {'status': 'unavailable', 'error_type': type(error).__name__,
                                'seconds': round(time.monotonic() - started, 4)}
            from core.ai_http import local_origin
            origin = local_origin(settings.LITMATE_OLLAMA_URL)
            tags, metrics = http(origin + '/api/tags')
            report['ollama'] = {**metrics, 'configured_model': settings.LITMATE_LOCAL_MODEL,
                'model_installed': settings.LITMATE_LOCAL_MODEL in [model.get('name') for model in tags.get('models', [])]}
            generated, metrics = http(origin + '/api/chat', {'model': settings.LITMATE_LOCAL_MODEL,
                'messages': [{'role': 'user', 'content': 'Responde únicamente con la palabra listo.'}],
                'stream': False, 'think': False, 'options': {'num_predict': 16, 'temperature': 0}}, timeout=30)
            report['ollama_inference'] = {**metrics, 'text': generated.get('message', {}).get('content', '')[:100],
                'done': generated.get('done'), 'eval_count': generated.get('eval_count')}
            results, metrics = http('http://127.0.0.1:8080/search?' + urlencode({
                'q': 'El principito zorro', 'format': 'json', 'language': 'es',
                'engines': 'wikipedia,mwmbl,openlibrary'}))
            report['searxng'] = {**metrics, 'results': [{key: item.get(key) for key in ('title', 'url', 'engine')}
                for item in results.get('results', [])[:5]], 'result_count': len(results.get('results', [])),
                'unresponsive_engines': results.get('unresponsive_engines', [])}
            report['original_hashes'] = {name: hashlib.sha256((settings.BASE_DIR / name).read_bytes()).hexdigest()
                for name in ('.env', 'data/literary_memory.sqlite3', 'data/literary_memory_rag.sqlite3')}
            connection.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=True, indent=2)
        print(json.dumps({key: report[key] for key in ('mysql', 'rag', 'ollama', 'ollama_inference')}, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
