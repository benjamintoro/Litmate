"""Demo WSGI restringida en localhost; jamás instala o activa un túnel."""
import argparse
from contextlib import closing
import getpass
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent


def prepare_workspace(folder, config):
    """Snapshots incrementales de arranque; nunca reemplaza copias existentes."""
    from scripts.knowledge.knowledge_campaign import STORES, sqlite_snapshot
    folder = Path(folder).resolve()
    if folder == ROOT or not folder.is_relative_to(ROOT / '.testtmp'):
        raise ValueError('La carpeta de demo debe estar dentro de .testtmp, separada de los datos originales.')
    marker = folder / 'demo-owner.json'
    if folder.exists() and not marker.is_file():
        raise ValueError('La carpeta existe y no pertenece a este lanzador; utiliza una nueva.')
    if marker.exists() and json.loads(marker.read_text(encoding='utf-8')) != {'owner': 'litmate-demo-v1'}:
        raise ValueError('Marcador de demo inválido.')
    if shutil.disk_usage(ROOT).free < 1024 * 1024 * 1024:
        raise ValueError('Se requiere al menos 1 GiB libre para preparar las copias.')
    folder.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        with marker.open('x', encoding='utf-8') as stream:
            json.dump({'owner': 'litmate-demo-v1'}, stream)
    overrides = {}
    for key in (*STORES, 'LITMATE_AI_RUNTIME_DB', 'LITMATE_AI_STREAM_DB', 'LITMATE_AI_ANSWER_CACHE_DB'):
        target = folder / (key.lower() + '.sqlite3')
        original = getattr(config, key, None)
        if not original and key == 'LITMATE_LITERARY_MEMORY_RAG_DB':
            original = ROOT / 'data' / 'literary_memory_rag.sqlite3'
        # Public evidence/indexes and provider cooldowns are copied, private
        # answer and streaming state start empty in the demonstration.
        copy_source = key in STORES or key == 'LITMATE_AI_RUNTIME_DB'
        if copy_source and original and Path(original).is_file() and not target.exists():
            sqlite_snapshot(Path(original), target)
        if target.exists():
            with closing(sqlite3.connect(target.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('Una copia de demo no pasó quick_check; conserva la carpeta y usa otra.')
        overrides[key] = target
    for name in ('sessions', 'media', 'logs'):
        (folder / name).mkdir(exist_ok=True)
    return folder, overrides


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modo', choices=('local', 'https'), default='local')
    parser.add_argument('--host', default='', help='DNS exacto de Tailscale, sólo para modo https.')
    parser.add_argument('--puerto', type=int, default=8002)
    parser.add_argument('--carpeta', type=Path, default=ROOT / '.testtmp' / 'demo-20261103')
    parser.add_argument('--comprobar', action='store_true', help='Verifica perfil y MySQL, no inicia servidor.')
    parser.add_argument('--comprobar-despliegue', action='store_true',
                        help='Ejecuta check --deploy con este perfil; combinar con --comprobar para salir.')
    parser.add_argument('--google-books-sin-facturacion', action='store_true')
    args = parser.parse_args(argv)
    if not 1024 <= args.puerto <= 65535:
        parser.error('Puerto local inválido.')
    from iniciar_mysql_local import local_database_environment
    password = getpass.getpass('Contraseña MySQL local (oculta): ')
    with local_database_environment(password, google_books_no_billing=args.google_books_sin_facturacion):
        password = None
        # Establish overrides before base settings read dotenv. They live only
        # in this dedicated process; development and TiDB settings are untouched.
        os.environ.update(DEBUG='False', SECRET_KEY=secrets.token_urlsafe(64),
            DJANGO_SETTINGS_MODULE='litmate_project.demo_settings', LITMATE_DEMO_MODE=args.modo,
            LITMATE_DEMO_HOST=args.host, LITMATE_DEMO_WORKSPACE=str(args.carpeta.resolve()))
        import django
        django.setup()
        from django.conf import settings
        from django.test import override_settings
        from django.db import connection
        from core.demo_gateway import build_demo_application
        folder, stores = prepare_workspace(args.carpeta, settings)
        stores['LOGGING'] = settings.LOGGING
        with override_settings(**stores):
            gate_password = getpass.getpass('Contraseña de acceso demo, mínimo 16 caracteres (oculta): ')
            application = build_demo_application(gate_password)
            gate_password = None
            with connection.cursor() as cursor:
                cursor.execute('SELECT DATABASE(), @@session.transaction_read_only')
                database, read_only = cursor.fetchone()
                cursor.execute('SELECT COUNT(*) FROM core_libro')
                books = cursor.fetchone()[0]
            if database != 'litmate_db' or not read_only:
                raise ValueError('La demo requiere MySQL local en modo de sesión de sólo lectura.')
            from django.core.management import call_command
            call_command('check', deploy=args.comprobar_despliegue, databases=['default'], verbosity=0)
            print(json.dumps({'debug': settings.DEBUG, 'database': database, 'mysql_read_only': bool(read_only),
                'books': books, 'mode': args.modo, 'bind': '127.0.0.1:' + str(args.puerto),
                'public_access_activated': False, 'workspace': str(folder)}, ensure_ascii=True), flush=True)
            if args.comprobar:
                return 0
            from waitress import create_server
            # The remote mode assumes TLS termination by the explicitly
            # configured HTTPS tunnel. Incoming forwarded headers are ignored.
            server = create_server(application, host='127.0.0.1', port=args.puerto, threads=8,
                url_scheme='https' if args.modo == 'https' else 'http',
                clear_untrusted_proxy_headers=True, channel_timeout=90,
                max_request_body_size=65536, ident='LitMate demo')
            # Comprobar el socket real, además de la configuración solicitada.
            actual_address, actual_port = server.socket.getsockname()[:2]
            if actual_address != '127.0.0.1' or actual_port != args.puerto:
                server.close()
                raise ValueError('El servidor no quedó limitado al destino loopback esperado.')
            print(json.dumps({'actual_listener': actual_address + ':' + str(actual_port),
                              'public_access_activated': False}), flush=True)
            server.run()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        # Controlled launcher errors only; never print database connection args.
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
