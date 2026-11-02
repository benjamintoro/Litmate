"""Start LitMate explicitly on local MySQL without editing .env or migrating."""
import argparse
from contextlib import contextmanager
import getpass
import json
import os
from pathlib import Path
import sys

LOCAL_DATABASE_ENV = {'DB_ENGINE': 'mysql', 'DB_MYSQL_DRIVER': 'mysqlclient',
    'DB_NAME': 'litmate_db', 'DB_USER': 'litmate_app', 'DB_HOST': '127.0.0.1',
    'DB_PORT': '3306', 'DB_SSL_CA': ''}


@contextmanager
def local_database_environment(password, environ=None, *, development_http=False,
                               google_books_no_billing=False):
    """Override only this process; never inherit the remote database password."""
    env = os.environ if environ is None else environ
    if not password:
        raise ValueError('Introduce la contraseña MySQL local en el prompt oculto.')
    values = {**LOCAL_DATABASE_ENV, 'DB_PASSWORD': password}
    if development_http:
        values['DEBUG'] = 'True'
    if google_books_no_billing:
        # Declaración explícita del operador, sólo para este proceso. No cambia
        # credenciales, .env ni el bloqueo predeterminado en otros arranques.
        values.update(LITMATE_GOOGLE_BOOKS_CONFIRMED_NO_BILLING='True',
                      LITMATE_USE_GOOGLE_BOOKS_API='True')
    old = {key: env.get(key) for key in values}
    try:
        env.update(values)
        yield
    finally:
        for key, value in old.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--solo-verificar', action='store_true', help='Run real HTTP/SSE smoke checks, then exit.')
    mode.add_argument('--verificar-y-servir', action='store_true', help='Verify, then leave Django running.')
    parser.add_argument('--puerto', type=int, default=8000)
    parser.add_argument('--http-desarrollo', action='store_true',
                        help='Explicit localhost HTTP mode with DEBUG=True, only for this process.')
    parser.add_argument('--google-books-sin-facturacion', action='store_true',
                        help='Activa Google Books en este proceso tras confirmar que su proyecto no tiene facturación vinculada.')
    args = parser.parse_args(argv)
    if 'litmate_project.settings' in sys.modules:
        raise RuntimeError('Ejecuta el lanzador en un proceso nuevo, antes de cargar Django.')
    password = os.environ.get('LITMATE_MYSQL_PASSWORD')
    if password is None:
        password = getpass.getpass('Contraseña MySQL local (no se muestra ni guarda): ')
    with local_database_environment(password, development_http=args.http_desarrollo,
                                    google_books_no_billing=args.google_books_sin_facturacion):
        password = None
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'litmate_project.settings')
        import django
        django.setup()
        from django.conf import settings
        from django.db import connection
        from django.core.management import call_command
        from django.db.migrations.executor import MigrationExecutor
        cfg = settings.DATABASES['default']
        if (cfg['ENGINE'] != 'django.db.backends.mysql' or cfg['NAME'] != 'litmate_db'
                or cfg['HOST'] != '127.0.0.1' or str(cfg['PORT']) != '3306'):
            raise RuntimeError('Django no seleccionó el destino MySQL local esperado.')
        with connection.cursor() as cursor:
            cursor.execute('SELECT DATABASE(), VERSION(), @@port')
            name, version, port = cursor.fetchone()
        if name != 'litmate_db' or int(port) != 3306 or 'tidb' in version.lower():
            raise RuntimeError('El servidor real no coincide con el MySQL local esperado.')
        executor = MigrationExecutor(connection)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            raise RuntimeError('Hay migraciones pendientes. Este lanzador no las ejecuta.')
        call_command('check', databases=['default'])
        print(json.dumps({'engine': cfg['ENGINE'], 'database': name, 'host': cfg['HOST'],
                          'port': port, 'version': version,
                          'driver': connection.connection.__class__.__module__}), flush=True)
        if args.solo_verificar or args.verificar_y_servir:
            from core.mysql_activation import verify_activation
            result = verify_activation()
            print(json.dumps({'activation_verified': result['passed'], 'report': result['report']}), flush=True)
            if not result['passed']:
                return 1
        if not args.solo_verificar:
            print('LitMate con MySQL local: http://127.0.0.1:' + str(args.puerto) + '/', flush=True)
            call_command('runserver', '127.0.0.1:' + str(args.puerto), use_reloader=False)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        pass
    except Exception as error:
        # Driver errors can contain connection details. Do not dump settings/tracebacks.
        print(json.dumps({'startup_failed': True, 'error_class': type(error).__name__,
            'error_code': error.args[0] if error.args and isinstance(error.args[0], int) else None,
            'note': 'No se importaron datos ni se cambió .env. Revisa la configuración local.'}), file=sys.stderr)
        raise SystemExit(1)
