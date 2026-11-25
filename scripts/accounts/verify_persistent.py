"""Abre Django en un proceso nuevo y comprueba la copia sin escribir ni servirla."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from scripts.accounts.promote_stage import inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    database, source = args.database.resolve(), args.source.resolve()
    if args.output.exists() or not database.is_relative_to(root/'data/accounts') or not source.is_relative_to(root/'.testtmp'):
        parser.error('Destino privado y fuente aislada requeridos; usa un informe nuevo.')
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    expected = inventory(source)
    if inventory(database) != expected:
        raise ValueError('La copia definitiva difiere del origen verificado.')
    from reader_accounts.signing_key import load_key
    key = load_key(database)
    os.environ.update(DB_ENGINE='sqlite', DB_SQLITE_PATH=str(root/'.testtmp/unused-verification.sqlite3'),
        DJANGO_SETTINGS_MODULE='litmate_project.reader_settings', LITMATE_DEMO_MODE='local',
        LITMATE_DEMO_WORKSPACE=str(root/'.testtmp/unused-verification'), LITMATE_ACCOUNTS_DB=str(database),
        SECRET_KEY=key)
    import django
    django.setup()
    from django.conf import settings
    # URI mode=ro se establece ANTES de la primera conexión al alias accounts.
    settings.DATABASES['accounts']['NAME'] = database.as_uri()+'?mode=ro'
    settings.DATABASES['accounts']['OPTIONS'] = {'uri': True, 'timeout': 10}
    from django.contrib.auth.models import User
    from django.contrib.auth.hashers import identify_hasher
    from django.db import connections
    from core.models import LibroFavorito, ListaLectura, ConversacionIA, MensajeIA
    users = list(User.objects.order_by('pk').values_list('pk', 'password'))
    algorithms = {}
    unusable = 0
    for _, password in users:
        if password.startswith('!'):
            unusable += 1
        else:
            algorithm = identify_hasher(password).algorithm
            algorithms[algorithm] = algorithms.get(algorithm, 0) + 1
    counts = {m._meta.db_table: m.objects.count() for m in (User, LibroFavorito, ListaLectura, ConversacionIA, MensajeIA)}
    connections.close_all()
    if hashlib.sha256(database.read_bytes()).hexdigest() != before:
        raise ValueError('El archivo cambió durante la verificación de lectura.')
    report = {'django_read_only_reopened': True, 'accounts_router': True, 'counts': counts,
        'all_tables_identical': True, 'password_fields_identical': True, 'password_algorithms': algorithms,
        'unusable_passwords_preserved': unusable, 'database_unchanged': True, 'public_services_started': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
