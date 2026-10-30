"""Comprobación optativa de sólo lectura: Django/MySQL y servicios locales.

Ejecutar desde raíz: python -m scripts.repository.verify_runtime --output ...
Solicita la contraseña oculta; no la escribe en archivos ni argumentos.
"""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[2]


def service_health():
    results = {}
    opener = build_opener(ProxyHandler({}))
    for name, url in (('ollama', 'http://127.0.0.1:11434/api/tags'),
                      ('searxng', 'http://127.0.0.1:8080/search?q=historia+medieval&format=json')):
        try:
            with opener.open(url, timeout=6) as response:
                data = json.loads(response.read(1024 * 1024))
            if name == 'ollama':
                results[name] = {'available': isinstance(data.get('models'), list),
                                 'local_models': [item.get('name') for item in data.get('models', [])]}
            else:
                results[name] = {'available': isinstance(data.get('results'), list),
                    'json_results': len(data.get('results', [])),
                    'engines_unavailable': len(data.get('unresponsive_engines', []))}
        except Exception as error:
            results[name] = {'available': False, 'error_class': type(error).__name__}
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('El informe ya existe; usa otro nombre.')
    from iniciar_mysql_local import local_database_environment
    password = getpass.getpass('Contraseña MySQL local (no se muestra ni guarda): ')
    result = {'database_modified': False, 'credentials_written': False}
    try:
        with local_database_environment(password):
            password = None
            os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'litmate_project.settings')
            import django
            django.setup()
            from django.conf import settings
            from django.db import connection
            from django.db.migrations.executor import MigrationExecutor
            from django.urls import resolve
            cfg = settings.DATABASES['default']
            if (cfg['ENGINE'] != 'django.db.backends.mysql' or cfg['NAME'] != 'litmate_db'
                    or cfg['HOST'] != '127.0.0.1' or str(cfg['PORT']) != '3306'):
                raise RuntimeError('El destino no es MySQL local.')
            with connection.cursor() as cursor:
                cursor.execute('SET SESSION TRANSACTION READ ONLY')
                cursor.execute('SELECT DATABASE(), VERSION(), @@port')
                name, version, port = cursor.fetchone()
                cursor.execute('SHOW TABLES')
                tables = [row[0] for row in cursor.fetchall()]
                counts = {}
                for table in tables:
                    cursor.execute('SELECT COUNT(*) FROM ' + connection.ops.quote_name(table))
                    counts[table] = cursor.fetchone()[0]
            result['mysql'] = {'engine': cfg['ENGINE'], 'database': name, 'port': port,
                'version': version, 'driver': connection.connection.__class__.__module__,
                'read_only_session': True, 'tables': len(tables), 'rows': sum(counts.values()),
                'counts': counts}
            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
            result['migrations'] = {'pending': len(plan), 'applied': len(executor.loader.applied_migrations),
                'application_labels': sorted({app for app, migration in executor.loader.disk_migrations
                                              if app in {'core', 'suscripciones'}})}
            # Ejecuta la entrada pública real con el mismo entorno sólo en el hijo.
            check = subprocess.run([sys.executable, '-B', str(ROOT / 'manage.py'), 'check', '--database', 'default'],
                cwd=ROOT, capture_output=True, text=True, timeout=30)
            result['manage_py_check'] = {'returncode': check.returncode,
                'passed': check.returncode == 0}
            from django.apps import apps
            result['orm_counts'] = {name: apps.get_model('core', name).objects.count()
                                   for name in ('Libro', 'ConversacionIA', 'MensajeIA')}
            result['chat_url_module'] = resolve('/chatbot_query/').func.__module__
            for module in ('core.literary_ai', 'core.local_llm', 'core.local_rag',
                           'core.literary_memory', 'core.literary_quality', 'core.literary_search'):
                __import__(module)
            result['ai_imports'] = 'ok'
            connection.close()
            result['passed'] = check.returncode == 0 and not plan and name == 'litmate_db'
    except Exception as error:
        # No copiar mensajes del driver, entorno, traceback ni configuraciones privadas.
        result.update(passed=False, error_class=type(error).__name__)
    result['services'] = service_health()
    result['env_sha256'] = hashlib.sha256((ROOT / '.env').read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key not in {'mysql', 'env_sha256'}}, ensure_ascii=True))
    return 0 if result.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
