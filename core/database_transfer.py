"""Verified, additive backups and database transfer. No writes to the source.

Snapshots contain private data. They belong outside version control. DDL is
executed only on a new SQLite copy or an explicitly requested, empty target.
"""
import base64
from contextlib import contextmanager, closing
from copy import deepcopy
from datetime import date, datetime, time, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3

from django.apps import apps
from django.db import connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder


class TransferError(ValueError):
    """Safe message, with no database values or credentials."""


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def json_write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def encode(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {'type': 'bytes', 'value': base64.b64encode(bytes(value)).decode()}
    if isinstance(value, (datetime, date, time, Decimal)):
        return {'type': type(value).__name__, 'value': str(value)}
    return value


def decode(value):
    if not isinstance(value, dict):
        return value
    kind, text = value['type'], value['value']
    return {'bytes': lambda: base64.b64decode(text), 'datetime': lambda: datetime.fromisoformat(text),
            'date': lambda: date.fromisoformat(text), 'time': lambda: time.fromisoformat(text),
            'Decimal': lambda: Decimal(text)}[kind]()


def fields_by_table():
    models = list(apps.get_models(include_auto_created=True)) + [MigrationRecorder.Migration]
    return {model._meta.db_table: {f.column: f for f in model._meta.local_concrete_fields}
            for model in models if model._meta.managed and not model._meta.proxy}


def canonical_row(table, columns, row):
    """Normalize backend representation, not content (case/accents stay exact)."""
    fields = fields_by_table().get(table, {})
    result = {}
    for name, value in zip(columns, row):
        field = fields.get(name)
        if value is not None and field:
            kind = field.get_internal_type()
            if kind == 'JSONField':
                value = json.loads(value) if isinstance(value, str) else value
            elif kind == 'DecimalField':
                value = format(Decimal(str(value)).quantize(Decimal(1).scaleb(-field.decimal_places)), 'f')
            elif kind in {'DateTimeField', 'DateField', 'TimeField'}:
                if isinstance(value, str):
                    parser = {'DateTimeField': datetime, 'DateField': date, 'TimeField': time}[kind]
                    value = parser.fromisoformat(value)
                value = value.isoformat()
            elif kind == 'BooleanField':
                value = bool(value)
            elif kind == 'FloatField':
                value = float(value)
        result[name] = encode(value)
    return json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def fingerprint(table, columns, rows, pk):
    values, keys = [], []
    for row in rows:
        text = canonical_row(table, columns, row)
        values.append(hashlib.sha256(text.encode()).hexdigest())
        keys.append(hashlib.sha256(canonical_row(table, [pk], [row[columns.index(pk)]]).encode()).hexdigest())
    return {'count': len(values), 'rows_sha256': hashlib.sha256(''.join(sorted(values)).encode()).hexdigest(),
            'keys_sha256': hashlib.sha256(''.join(sorted(keys)).encode()).hexdigest()}


def inspect_table(connection, table):
    with connection.cursor() as cursor:
        cursor.execute('SELECT * FROM ' + connection.ops.quote_name(table) + ' WHERE 1=0')
        columns = [item[0] for item in cursor.description]
        constraints = connection.introspection.get_constraints(cursor, table)
    primary = [v['columns'] for v in constraints.values() if v.get('primary_key')]
    if len(primary) != 1 or len(primary[0]) != 1:
        raise TransferError('Se requiere una clave primaria simple por tabla: ' + table)
    return columns, primary[0][0], constraints


def table_rows(connection, table):
    with connection.cursor() as cursor:
        cursor.execute('SELECT * FROM ' + connection.ops.quote_name(table))
        return cursor.fetchall()


def source_identity(connection):
    config = connection.settings_dict
    return hashlib.sha256(json.dumps({k: str(config.get(k, '')) for k in
        ('ENGINE', 'NAME', 'HOST', 'PORT')}, sort_keys=True).encode()).hexdigest()


@contextmanager
def readonly_snapshot(connection):
    """Repeatable-read data snapshot; no DDL or DML on the source."""
    if connection.in_atomic_block:
        raise TransferError('El respaldo requiere una conexión sin transacciones previas.')
    if connection.vendor == 'mysql':
        with connection.cursor() as cursor:
            cursor.execute('SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    with transaction.atomic(using=connection.alias):
        if connection.vendor == 'sqlite':
            with connection.cursor() as cursor:
                cursor.execute('PRAGMA query_only=ON')
        try:
            yield
        finally:
            transaction.set_rollback(True, using=connection.alias)
    if connection.vendor == 'sqlite':
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA query_only=OFF')


def export_database(alias, destination):
    connection = connections[alias]
    if connection.vendor == 'sqlite' and not Path(connection.settings_dict['NAME']).is_file():
        raise TransferError('La base SQLite original no existe; no se crea una base vacía.')
    destination = Path(destination)
    destination.mkdir(exist_ok=False)
    tables = {}
    with readonly_snapshot(connection):
        for table in sorted(connection.introspection.table_names()):
            if not table.replace('_', '').isalnum():
                raise TransferError('Nombre de tabla no admitido.')
            columns, pk, constraints = inspect_table(connection, table)
            with connection.cursor() as cursor:
                if connection.vendor == 'mysql':
                    cursor.execute('SHOW CREATE TABLE ' + connection.ops.quote_name(table))
                    schema_sql = cursor.fetchone()[1]
                    if 'ENGINE=InnoDB' not in schema_sql:
                        raise TransferError('Respaldo consistente requiere InnoDB en ' + table)
                    match = re.search(r'AUTO_INCREMENT=(\d+)', schema_sql)
                    next_id = int(match.group(1)) if match else None
                else:
                    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=%s", [table])
                    schema_sql = cursor.fetchone()[0]
                    next_id = None
                    if 'AUTOINCREMENT' in schema_sql.upper():
                        cursor.execute('SELECT seq FROM sqlite_sequence WHERE name=%s', [table])
                        sequence = cursor.fetchone()
                        next_id = sequence[0] + 1 if sequence else 1
            rows = table_rows(connection, table)
            path = destination / (table + '.jsonl.gz')
            with gzip.open(path, 'xt', encoding='utf-8') as stream:
                for row in rows:
                    stream.write(json.dumps([encode(v) for v in row], ensure_ascii=False) + '\n')
            tables[table] = {**fingerprint(table, columns, rows, pk), 'columns': columns, 'pk': pk,
                'constraints': constraints, 'schema_sql': schema_sql, 'next_id': next_id,
                'file': path.name, 'sha256': digest(path)}
    return {'vendor': connection.vendor, 'identity': source_identity(connection), 'tables': tables}


def safe_file(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root or path.is_symlink() or not path.is_file():
        raise TransferError('Ruta de respaldo inválida.')
    return path


def read_rows(root, table):
    path = safe_file(root, table['file'])
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        return [tuple(decode(v) for v in json.loads(line)) for line in stream]


def verify_export(root, metadata):
    for name, table in metadata['tables'].items():
        path = safe_file(root, table['file'])
        if digest(path) != table['sha256']:
            raise TransferError('Archivo alterado: ' + name)
        result = fingerprint(name, table['columns'], read_rows(root, table), table['pk'])
        if any(result[k] != table[k] for k in result):
            raise TransferError('Conteos/claves/contenido no coinciden: ' + name)
    verify_relations(root, metadata)


def verify_relations(root, metadata):
    """Check foreign keys even when the original schema did not enforce them."""
    tables = metadata['tables']
    data = {name: read_rows(root, value) for name, value in tables.items()}
    for name, table in tables.items():
        for value in table['constraints'].values():
            foreign = value.get('foreign_key')
            if not foreign:
                continue
            target, column = foreign
            if target not in tables:
                raise TransferError('Referencia a tabla ausente: ' + name)
            allowed = {row[tables[target]['columns'].index(column)] for row in data[target]}
            index = table['columns'].index(value['columns'][0])
            if any(row[index] is not None and row[index] not in allowed for row in data[name]):
                raise TransferError('Relaciones huérfanas en ' + name)


@contextmanager
def temporary_alias(name, config):
    if name in connections.databases:
        raise TransferError('Alias ocupado.')
    value = deepcopy(connections['default'].settings_dict)
    value.update(config)
    value.update(ATOMIC_REQUESTS=False, AUTOCOMMIT=True, CONN_MAX_AGE=0)
    connections.databases[name] = value
    try:
        yield connections[name]
    finally:
        connections[name].close()
        del connections[name]
        del connections.databases[name]


def insertion_order(tables):
    remaining, result = set(tables) - {'django_migrations'}, []
    while remaining:
        ready = sorted(name for name in remaining if not any(
            c.get('foreign_key') and c['foreign_key'][0] in remaining
            for c in tables[name]['constraints'].values()))
        if not ready:
            raise TransferError('Relaciones cíclicas: se requiere revisar el orden, sin desactivar claves.')
        result.extend(ready)
        remaining.difference_update(ready)
    return result


def check_schema(connection, metadata):
    tables = set(connection.introspection.table_names())
    if tables != set(metadata['tables']):
        raise TransferError('El conjunto de tablas no coincide con el respaldo.')
    for name, expected in metadata['tables'].items():
        columns, pk, constraints = inspect_table(connection, name)
        if set(columns) != set(expected['columns']) or pk != expected['pk']:
            raise TransferError('Esquema/clave incompatible: ' + name)
        # Names vary between backends; semantics must not.
        def signatures(items):
            return {(tuple(v['columns']), tuple(v['foreign_key']) if v.get('foreign_key') else None,
                     bool(v.get('unique') or v.get('primary_key')), bool(v.get('primary_key')))
                    for v in items.values() if v.get('foreign_key') or v.get('unique') or v.get('primary_key')}
        if not signatures(expected['constraints']).issubset(signatures(constraints)):
            raise TransferError('Restricciones únicas/relacionales incompatibles: ' + name)
        indexed = {tuple(c['columns']) for c in constraints.values()
                   if c.get('index') or c.get('unique') or c.get('primary_key')}
        if any(tuple(c['columns']) not in indexed for c in expected['constraints'].values()
               if c.get('index') and not c.get('foreign_key')):
            raise TransferError('Índices incompatibles: ' + name)


def mysql_collation_preflight(connection, root, metadata):
    """Use MySQL's own equality rules, before creating any target tables."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT @@collation_database')
        collation = cursor.fetchone()[0]
        if not re.fullmatch(r'utf8mb4_[a-zA-Z0-9_]+', collation):
            raise TransferError('Cotejamiento MySQL inesperado.')
        for name, table in metadata['tables'].items():
            fields = fields_by_table().get(name, {})
            for constraint in table['constraints'].values():
                columns = constraint['columns']
                if not constraint.get('unique') or constraint.get('primary_key') or not any(
                        fields.get(c) and fields[c].get_internal_type() in {'CharField', 'SlugField', 'EmailField'}
                        for c in columns):
                    continue
                rows = [[row[table['columns'].index(c)] for c in columns] for row in read_rows(root, table)]
                rows = [row for row in rows if all(v is not None for v in row)]
                if len(rows) < 2:
                    continue
                if len(rows) > 5000:
                    raise TransferError('Se requiere revisar una restricción única de más de 5000 filas: ' + name)
                aliases = ['c' + str(i) for i in range(len(columns))]
                select = 'SELECT ' + ', '.join('CAST(%s AS CHAR CHARACTER SET utf8mb4) COLLATE '
                    + collation + ' AS ' + alias for alias in aliases)
                sql = ('SELECT 1 FROM (' + ' UNION ALL '.join([select] * len(rows))
                       + ') AS candidates GROUP BY ' + ', '.join(aliases) + ' HAVING COUNT(*) > 1 LIMIT 1')
                cursor.execute(sql, [str(value) for row in rows for value in row])
                if cursor.fetchone():
                    raise TransferError('El cotejamiento agrupa claves distintas en ' + name
                                        + '; revisar un cotejamiento sensible antes de importar.')


def fresh_mysql_metadata(connection):
    """MySQL 8 caches TABLES/SHOW statistics; validation needs current counters.

    This is a session setting, not a server/global or schema modification.
    TiDB/MariaDB do not expose this MySQL-specific variable.
    """
    if (connection.vendor == 'mysql' and connection.mysql_version >= (8, 0)
            and not connection.mysql_is_mariadb
            and 'tidb' not in connection.mysql_server_info.lower()):
        with connection.cursor() as cursor:
            cursor.execute('SET SESSION information_schema_stats_expiry=0')


def next_id_value(connection, name):
    """Return the next usable/reserved ID, never SQLite's last-used value."""
    with connection.cursor() as cursor:
        if connection.vendor == 'sqlite':
            cursor.execute('SELECT seq FROM sqlite_sequence WHERE name=%s', [name])
            sequence = cursor.fetchone()
            return sequence[0] + 1 if sequence else 1
        if 'tidb' in connection.mysql_server_info.lower():
            # TiDB v8.5.3 returns 0 in SHOW TABLE STATUS.Auto_increment.
            # SHOW CREATE exposes the allocator high watermark used at export.
            # Compare the same authoritative quantity on both sides.
            cursor.execute('SHOW CREATE TABLE ' + connection.ops.quote_name(name))
            match = re.search(r'AUTO_INCREMENT=(\d+)', cursor.fetchone()[1])
            if not match:
                raise TransferError('TiDB no informa un próximo contador verificable: ' + name)
            return int(match.group(1))
        cursor.execute('SHOW TABLE STATUS WHERE Name=%s', [name])
        status = dict(zip([v[0] for v in cursor.description], cursor.fetchone()))
        if not status.get('Auto_increment'):
            raise TransferError('MySQL no informa un próximo contador verificable: ' + name)
        return status['Auto_increment']


def compare_database(connection, root, metadata, *, stage='comparison', trace=None):
    fresh_mysql_metadata(connection)
    check_schema(connection, metadata)
    result = {}
    for name, table in metadata['tables'].items():
        if name == 'django_migrations':
            expected = {(r[table['columns'].index('app')], r[table['columns'].index('name')])
                        for r in read_rows(root, table)}
            actual = set(MigrationRecorder(connection).applied_migrations())
            if actual != expected:
                raise TransferError('El historial de migraciones difiere.')
            result[name] = {'count': len(actual), 'migration_names_match': True,
                            'note': 'IDs/fechas del historial se generan para el esquema nuevo.'}
            continue
        columns, pk, _ = inspect_table(connection, name)
        rows = table_rows(connection, name)
        actual = fingerprint(name, columns, rows, pk)
        if any(actual[k] != table[k] for k in actual):
            raise TransferError('Diferencia de conteo/claves/contenido en ' + name)
        next_id = table.get('next_id')
        if next_id:
            actual_next = next_id_value(connection, name)
            maximum = max((row[columns.index(pk)] for row in rows), default=None)
            if trace is not None:
                trace.append({'table': name, 'stage': stage, 'vendor': connection.vendor,
                    'rows': len(rows), 'max_id': maximum, 'expected_next_id': next_id,
                    'actual_next_id': actual_next, 'in_atomic_block': connection.in_atomic_block,
                    'autocommit': connection.get_autocommit()})
            if actual_next < next_id:
                raise TransferError('Contador de IDs inferior al origen: ' + name)
            actual['next_id'] = actual_next
            actual['max_id'] = maximum
        result[name] = actual
    connection.check_constraints()
    return result


def create_final_schema(connection, *, collect_sql=False):
    """Restore a migrated snapshot directly, without replaying historical DROP.

    Only use on an empty destination. Data migrations are not replayed: their
    completed data is already present in the verified snapshot being restored.
    Constraints/indexes and the full migration set are checked afterwards.
    """
    if not collect_sql and connection.introspection.table_names():
        raise TransferError('El esquema final sólo se crea en un destino vacío.')
    loader = MigrationExecutor(connection).loader
    state = loader.project_state(loader.graph.leaf_nodes())
    models = {m._meta.db_table: m for m in state.apps.get_models()
              if m._meta.managed and not m._meta.proxy and not m._meta.swapped}
    pending, ordered = set(models), []
    while pending:
        ready = []
        for name in sorted(pending):
            model = models[name]
            dependencies = {f.remote_field.model._meta.db_table for f in
                [*model._meta.local_fields, *model._meta.local_many_to_many]
                if f.is_relation and f.remote_field and hasattr(f.remote_field.model, '_meta')}
            if not (dependencies - {name}) & pending:
                ready.append(name)
        if not ready:
            raise TransferError('Esquema con relaciones cíclicas: se necesita un plan de creación explícito.')
        ordered.extend(ready)
        pending.difference_update(ready)
    with connection.schema_editor(collect_sql=collect_sql) as editor:
        for name in ordered:
            editor.create_model(models[name])
        editor.create_model(MigrationRecorder.Migration)
    if collect_sql:
        return editor.collected_sql
    recorder = MigrationRecorder(connection)
    for app, name in sorted(loader.graph.nodes):
        recorder.record_applied(app, name)


def import_database(connection, root, metadata, *, resume_empty=False, trace=None):
    """Never merge into an occupied DB. MySQL DDL cannot be rolled back."""
    verify_export(root, metadata)
    occupied = bool(connection.introspection.table_names())
    if occupied:
        if not resume_empty:
            raise TransferError('El destino contiene tablas; no se sobrescribe ni se mezcla.')
        check_schema(connection, metadata)
        with connection.cursor() as cursor:
            for name in metadata['tables']:
                if name == 'django_migrations':
                    continue
                cursor.execute('SELECT COUNT(*) FROM ' + connection.ops.quote_name(name))
                if cursor.fetchone()[0]:
                    raise TransferError('Reanudación rechazada: hay datos existentes en ' + name)
        migrations = metadata['tables']['django_migrations']
        expected = {(row[migrations['columns'].index('app')], row[migrations['columns'].index('name')])
                    for row in read_rows(root, migrations)}
        if set(MigrationRecorder(connection).applied_migrations()) != expected:
            raise TransferError('Reanudación rechazada: historial de esquema diferente.')
    if connection.vendor == 'mysql':
        mysql_collation_preflight(connection, root, metadata)
    order = insertion_order(metadata['tables'])
    if not occupied:
        create_final_schema(connection)
    check_schema(connection, metadata)
    if connection.vendor == 'mysql':
        # Only the newly-created empty tables are altered, before data DML.
        for name in order:
            next_id = metadata['tables'][name].get('next_id')
            if next_id:
                with connection.cursor() as cursor:
                    cursor.execute('ALTER TABLE ' + connection.ops.quote_name(name)
                                   + ' AUTO_INCREMENT = ' + str(int(next_id)))
    with transaction.atomic(using=connection.alias):
        for name in order:
            table = metadata['tables'][name]
            columns = ', '.join(connection.ops.quote_name(v) for v in table['columns'])
            sql = ('INSERT INTO ' + connection.ops.quote_name(name) + ' (' + columns + ') VALUES ('
                   + ', '.join(['%s'] * len(table['columns'])) + ')')
            rows = read_rows(root, table)
            if connection.vendor == 'sqlite':
                rows = [tuple(str(v) if isinstance(v, Decimal) else v for v in row) for row in rows]
            if rows:
                with connection.cursor() as cursor:
                    cursor.executemany(sql, rows)
            next_id = table.get('next_id')
            if next_id and connection.vendor == 'sqlite':
                with connection.cursor() as cursor:
                    cursor.execute('SELECT seq FROM sqlite_sequence WHERE name=%s', [name])
                    sequence = cursor.fetchone()
                    if sequence:
                        cursor.execute('UPDATE sqlite_sequence SET seq=%s WHERE name=%s',
                                       [max(sequence[0], next_id - 1), name])
                    else:
                        cursor.execute('INSERT INTO sqlite_sequence(name, seq) VALUES(%s, %s)',
                                       [name, next_id - 1])
        result = compare_database(connection, root, metadata, stage='target.before_commit', trace=trace)
    # Repeat after commit: success must describe durable rows, not an open transaction.
    return compare_database(connection, root, metadata, stage='target.after_commit', trace=trace)


def snapshot_sqlite(source, target):
    """Online backup API includes committed WAL content, unlike copyfile."""
    source, target = Path(source).resolve(), Path(target)
    if not source.is_file() or source.is_symlink() or target.exists():
        raise TransferError('SQLite origen ausente o destino ocupado.')
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=5)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise TransferError('Respaldo SQLite dañado.')
            if dst.execute('PRAGMA foreign_key_check').fetchall():
                raise TransferError('Respaldo SQLite con relaciones inválidas.')
            tables = [r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            counts = {t: dst.execute('SELECT COUNT(*) FROM "' + t.replace('"', '""') + '"').fetchone()[0]
                      for t in tables}
    return {'sha256': digest(target), 'counts': counts, 'integrity_check': 'ok'}


def create_backup(destination):
    from django.conf import settings
    destination = Path(destination).resolve()
    if any(destination.is_relative_to(Path(settings.BASE_DIR) / folder) for folder in ('data', 'media')):
        raise TransferError('El respaldo no puede quedar dentro de data ni media.')
    destination.mkdir(parents=True, exist_ok=False)
    # A partial directory never has a complete manifest and cannot be imported.
    metadata = export_database('default', destination / 'database')
    verify_export(destination / 'database', metadata)
    files, sqlite_files = {}, {}
    candidates = set()
    for name in ('data', 'media'):
        folder = Path(settings.BASE_DIR) / name
        candidates.update(p for p in folder.rglob('*') if p.is_file())
    candidates.update(Path(getattr(settings, k)) for k in dir(settings)
                      if k.startswith('LITMATE_') and k.endswith('_DB') and Path(getattr(settings, k)).is_file())
    for source in sorted({p.absolute() for p in candidates}):
        if source.is_symlink():
            raise TransferError('No se respaldan enlaces simbólicos.')
        if source.name.endswith(('-wal', '-shm', '-journal')):
            continue
        relative = (source.relative_to(settings.BASE_DIR) if source.is_relative_to(settings.BASE_DIR)
                    else Path('extra_stores') / (hashlib.sha256(str(source).encode()).hexdigest()[:16] + source.suffix))
        target = destination / 'files' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as stream:
            is_sqlite = stream.read(16) == b'SQLite format 3\x00'
        if is_sqlite:
            info = snapshot_sqlite(source, target)
            sqlite_files[str(relative)] = info
        else:
            before = digest(source)
            with source.open('rb') as src, target.open('xb') as dst:
                shutil.copyfileobj(src, dst)
            if before != digest(source) or before != digest(target):
                raise TransferError('Un archivo cambió durante el respaldo; repetir en una carpeta nueva.')
        files[str(relative)] = {'sha256': digest(target), 'bytes': target.stat().st_size}
    sqlite_path = destination / 'django.sqlite3'
    with temporary_alias('transfer_sqlite', {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(sqlite_path),
                         'HOST': '', 'PORT': '', 'USER': '', 'PASSWORD': '', 'OPTIONS': {}}) as target:
        copied = import_database(target, destination / 'database', metadata)
    manifest = {'format': 'litmate-backup-v1', 'complete': True,
        'created_at': datetime.now(timezone.utc).isoformat(), 'database': metadata,
        'sqlite_fallback': {'file': sqlite_path.name, 'sha256': digest(sqlite_path), 'tables': copied},
        'files': files, 'sqlite_stores': sqlite_files,
        'consistency': 'Django repeatable-read snapshot; each auxiliary SQLite has its own online snapshot.'}
    json_write(destination / 'manifest.json', manifest)
    verify_backup(destination)
    return manifest


def verify_backup(root):
    root = Path(root).resolve()
    manifest = json.loads(safe_file(root, 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 'litmate-backup-v1' or manifest.get('complete') is not True:
        raise TransferError('Respaldo incompleto.')
    verify_export(root / 'database', manifest['database'])
    fallback = safe_file(root, manifest['sqlite_fallback']['file'])
    if digest(fallback) != manifest['sqlite_fallback']['sha256']:
        raise TransferError('La copia SQLite cambió; no debe utilizarse como base de trabajo.')
    for relative, info in manifest['files'].items():
        if digest(safe_file(root / 'files', relative)) != info['sha256']:
            raise TransferError('Archivo de respaldo alterado.')
    return manifest


def source_unchanged(root, manifest, *, trace=None):
    connection = connections['default']
    if source_identity(connection) != manifest['database']['identity']:
        raise TransferError('La configuración origen cambió desde el respaldo.')
    with readonly_snapshot(connection):
        compare_database(connection, Path(root) / 'database', manifest['database'],
                         stage='source_freshness.before_target_DDL', trace=trace)
