"""Ensayo social HTTPS con SQLite sintético, actualización y restauración."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import queue
import sqlite3
import ssl
import subprocess
import sys
import threading
import time

from scripts.accounts import production_smoke as smoke

ROOT = Path(__file__).resolve().parents[2]


def rows(database):
    """Inventario privado en memoria para verificar las filas preexistentes."""
    with closing(sqlite3.connect(database)) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {name: connection.execute('SELECT * FROM "' + name.replace('"', '""') + '" ORDER BY rowid').fetchall()
                for name, in tables}


def seed_and_upgrade(folder):
    smoke.seed(folder)
    from django.core.management import call_command
    from django.db import connections
    from django.db.migrations.executor import MigrationExecutor
    from core.models import Autor, Libro
    from reader_accounts.models import SocialProfile, SharedList, SharedReading
    from PIL import Image, ImageOps

    database = folder / 'accounts/users.sqlite3'
    connection = connections['accounts']
    MigrationExecutor(connection).migrate([('reader_accounts', '0003_paymentevent')])
    connection.close()
    baseline = rows(database)
    call_command('migrate', database='accounts', interactive=False, verbosity=0)
    connection.close()
    upgraded = rows(database)
    preserved = all(all(row in upgraded[table] for row in originals) for table, originals in baseline.items())
    if not preserved:
        raise AssertionError('Una fila anterior cambió durante la migración.')
    assert not SocialProfile.objects.exists()
    assert not SharedList.objects.exists()
    assert not SharedReading.objects.exists()
    author = Autor.objects.create(nombre='Mary Shelley')
    book = Libro.objects.create(autor=author, titulo='Frankenstein', google_book_id='community-frankenstein',
                               sinopsis='Una novela sobre creación y responsabilidad.')
    Libro.objects.create(autor=Autor.objects.create(nombre='Franz Kafka'),
                         titulo='La metamorfosis', google_book_id='community-metamorfosis')
    images = folder / 'uploads'
    images.mkdir()
    for name, source, bounds in [
        ('avatar', 'static/assets/img/avatar/feliz.png', (512, 512)),
        ('cover', 'static/assets/img/buscarlibros.jpg', (1280, 800)),
    ]:
        with Image.open(ROOT / source) as image:
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail(bounds)
            image.save(images / (name + '.jpg'), quality=85)
    connection.close()
    connections['default'].close()
    return {'old_rows_preserved': preserved, 'legacy_social_profiles_created': False,
            'legacy_readings_published': False, 'book_id': book.pk}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--browser-script', type=Path, required=True)
    parser.add_argument('--seed', action='store_true')
    args = parser.parse_args()
    folder = args.folder.resolve()
    if not folder.is_relative_to(ROOT / '.testtmp'):
        parser.error('Sólo se admiten carpetas de ensayo dentro de .testtmp.')
    if args.seed:
        report = seed_and_upgrade(folder)
        (folder / 'migration.json').write_text(json.dumps(report, indent=2), encoding='utf8')
        return
    output = args.output.resolve()
    if folder.exists() or output.exists() or not output.is_relative_to(ROOT / 'reports'):
        parser.error('Utiliza carpeta e informe nuevos de ensayo.')
    folder.mkdir(parents=True)
    (folder / 'accounts').mkdir()
    output.parent.mkdir(parents=True, exist_ok=True)
    cert, key = folder / 'tls.pem', folder / 'tls.key'
    subprocess.run([r'C:\Program Files\Git\usr\bin\openssl.exe', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
        '-keyout', str(key), '-out', str(cert), '-days', '1', '-subj', '/CN=litmate.example.test',
        '-addext', 'subjectAltName=DNS:litmate.example.test,IP:127.0.0.1'], check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    dependencies = smoke.ThreadingHTTPServer(('127.0.0.1', 0), smoke.Dependencies)
    threading.Thread(target=dependencies.serve_forever, daemon=True).start()
    backend = smoke.port()
    smoke.Proxy.backend = backend
    proxy = smoke.ThreadingHTTPServer(('127.0.0.1', 0), smoke.Proxy)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    proxy.socket = tls.wrap_socket(proxy.socket, server_side=True)
    origin = f'https://litmate.example.test:{proxy.server_address[1]}'
    env = smoke.environment(folder, origin, backend, dependencies.server_address[1])
    env['LITMATE_COMMUNITY_ENABLED'] = '1'
    env['LITMATE_COMMUNITY_TEST_IMAGES'] = str(folder / 'uploads')
    browser_report = output.with_name(output.stem + '_navegador.json')
    report = {'scope': 'isolated HTTPS with synthetic accounts and catalogue', 'production_touched': False,
              'checks': {}, 'origin': origin}
    checks = report['checks']
    stop = folder / 'runtime/stop.request'
    command = [sys.executable, '-B', str(ROOT / 'iniciar_produccion.py'), '--origin', origin, '--proxy', 'loopback-tls',
               '--port', str(backend), '--accounts-db', str(folder / 'accounts/users.sqlite3'),
               '--runtime', str(folder / 'runtime'), '--isolated', '--sqlite-catalog', str(folder / 'catalog.sqlite3')]
    process = None

    def start():
        if stop.exists():
            stop.unlink()
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, encoding='utf8', errors='replace')
        lines = queue.Queue()
        def read():
            for line in child.stdout:
                lines.put(line)
        threading.Thread(target=read, daemon=True).start()
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                if 'actual_listener' in lines.get(timeout=.2):
                    return child
            except queue.Empty:
                pass
            if child.poll() is not None:
                raise RuntimeError(child.stderr.read()[:1500])
        child.terminate()
        raise TimeoutError('No apareció el listener aislado.')

    def stop_child(child):
        stop.touch()
        child.wait(timeout=15)

    try:
        subprocess.run([sys.executable, '-B', '-m', 'scripts.accounts.community_acceptance', '--seed',
                        '--folder', str(folder), '--output', str(output), '--node', str(args.node),
                        '--browser-script', str(args.browser_script)], cwd=ROOT, env=env, check=True,
                       stdout=subprocess.DEVNULL)
        report['migration'] = json.loads((folder / 'migration.json').read_text(encoding='utf8'))
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
        process = start()
        subprocess.run([str(args.node), str(args.browser_script.resolve()), origin, str(output.parent),
                        str(browser_report), str(report['migration']['book_id'])],
                       cwd=ROOT, env=env, check=True, timeout=150)
        report['browser'] = json.loads(browser_report.read_text(encoding='utf8'))
        checks['browser'] = report['browser'].get('passed', False)
        before = rows(folder / 'accounts/users.sqlite3')
        stop_child(process)
        process = start()
        checks['same_persistent_rows_after_restart'] = rows(folder / 'accounts/users.sqlite3') == before
        # El navegador abre una sesión nueva tras el reinicio y comprueba perfil, publicación y biblioteca.
        subprocess.run([str(args.node), str(args.browser_script.resolve()), origin, str(output.parent),
                        str(browser_report.with_name(output.stem + '_reinicio.json')), str(report['migration']['book_id']),
                        'restart'], cwd=ROOT, env=env, check=True, timeout=90)
        checks['browser_after_restart'] = json.loads(
            browser_report.with_name(output.stem + '_reinicio.json').read_text(encoding='utf8')).get('passed', False)
        stop_child(process)
        process = None
        for action, destination in [
            ('crear', folder / 'accounts/users.sqlite3'),
            ('restaurar-nuevo', folder / 'restored/accounts/users.sqlite3'),
        ]:
            subprocess.run([sys.executable, '-B', '-m', 'scripts.accounts.backup_store', action,
                '--database', str(destination), '--folder', str(folder / 'backup')], cwd=ROOT, env=env,
                check=True, stdout=subprocess.DEVNULL)
        checks['restored_rows_equal'] = rows(folder / 'restored/accounts/users.sqlite3') == rows(folder / 'accounts/users.sqlite3')
        checks['no_provider_inference'] = smoke.Dependencies.llm_calls == 0
        report['passed'] = all(checks.values())
    except Exception as error:
        report['error'] = str(error)
        report['passed'] = False
    finally:
        if process is not None and process.poll() is None:
            stop_child(process)
        proxy.shutdown()
        dependencies.shutdown()
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf8')
    print(json.dumps({'passed': report.get('passed'), 'error': report.get('error'), 'checks': checks}))
    return 0 if report.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
