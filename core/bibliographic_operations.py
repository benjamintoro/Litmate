"""Operaciones administrativas acotadas y verificaciones; ninguna ruta pública."""
import gzip
import io
import json
import math
from pathlib import Path
import statistics
import time
import tracemalloc
from django.conf import settings
from django.db import connection
from django.core.management import call_command


def preserve_existing_rows(root, manifest):
    """Compara exactamente cada fila original; admite sólo nuevas PK adicionales."""
    from .database_transfer import decode, fingerprint, table_rows
    result = {}
    for table, info in manifest['database']['tables'].items():
        columns, pk = info['columns'], info['pk']
        with gzip.open(Path(root)/'database'/info['file'], 'rt', encoding='utf-8') as stream:
            original = [[decode(value) for value in json.loads(line)] for line in stream]
        # Sólo las tablas de metadatos Django pueden ganar filas con esta migración.
        actual = table_rows(connection, table)
        indices = [columns.index(pk)] if pk else []
        if indices:
            keys = {tuple(row[index] for index in indices) for row in original}
            old_actual = [row for row in actual if tuple(row[index] for index in indices) in keys]
        else:
            old_actual = actual
        current = fingerprint(table, columns, old_actual, pk)
        if any(current[key] != info[key] for key in current):
            raise ValueError('Una fila original cambió: ' + table)
        added = len(actual) - len(original)
        if added and table not in {'django_migrations', 'django_content_type', 'auth_permission'}:
            raise ValueError('Una tabla original recibió filas inesperadas: ' + table)
        result[table] = {'original_rows': len(original), 'unchanged': True, 'framework_metadata_added': added}
    connection.check_constraints()
    return result


def prepare_schema(root, manifest):
    from django.db.migrations.executor import MigrationExecutor
    from django.db.migrations.operations.models import CreateModel
    from .database_transfer import source_unchanged
    source_unchanged(root, manifest)
    executor = MigrationExecutor(connection)
    target = ('core', '0008_bibliographic_repository')
    plan = executor.migration_plan([target])
    if [(migration.app_label, migration.name) for migration, backwards in plan] != [target]:
        raise ValueError('El plan no es exactamente la nueva migración aditiva.')
    migration = plan[0][0]
    if (any(not isinstance(op, CreateModel) for op in migration.operations)
            or {op.name for op in migration.operations} != {'KBProjection','KBRecord','KBName','KBRelation','KBVersion'}):
        raise ValueError('Operación de esquema fuera del alcance.')
    sql = io.StringIO()
    call_command('sqlmigrate', 'core', '0008', stdout=sql)
    import re
    if re.search(r'\b(?:DROP|TRUNCATE|DELETE|RENAME)\b', sql.getvalue(), re.I):
        raise ValueError('SQL destructivo rechazado.')
    call_command('migrate', 'core', '0008', interactive=False, verbosity=0)
    call_command('check', databases=['default'], verbosity=0)
    call_command('makemigrations', check=True, dry_run=True, verbosity=0)
    integrity = preserve_existing_rows(root, manifest)
    return {'passed': True, 'new_tables': 5, 'destructive_statements': 0,
        'migration': list(target), 'integrity': integrity, 'sql_preview': sql.getvalue(),
        'original_rows_preserved': sum(value['original_rows'] for value in integrity.values())}


def project_and_audit(state_database, root, manifest, *, maximum=100, replay=False,
                      batch_size=25, max_seconds=60, max_storage_mb=16):
    from .bibliographic_repository import project_ledger, lookup_sources
    from .knowledge_models import KBRecord, KBVersion, KBName, KBRelation
    from evaluar_chat_http import memory_snapshot
    tracemalloc.start()
    start = time.monotonic()
    report = project_ledger(state_database, max_records=maximum, batch_size=batch_size,
                            max_seconds=max_seconds, replay=replay, max_storage_mb=max_storage_mb)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    examples, latencies = [], []
    from .ai_quick_answers import catalogue_lookup_answer
    for record in KBRecord.objects.filter(status='source_metadata', kind__in=['work','edition']).order_by('id')[:12]:
        tick = time.monotonic()
        sources = lookup_sources(record.label)
        answer = catalogue_lookup_answer('¿Quién escribió ' + record.label + '?', [], lookup_sources)
        latencies.append((time.monotonic() - tick) * 1000)
        if answer:
            examples.append({'title': record.label, 'question': '¿Quién escribió ' + record.label + '?',
                'answer': answer.text, 'status': answer.status, 'book_id': sources[0]['book_id'],
                'source_url': record.source_url, 'llm_calls': 0})
    integrity = preserve_existing_rows(root, manifest)
    with connection.cursor() as cursor:
        cursor.execute('SELECT TABLE_NAME,DATA_LENGTH,INDEX_LENGTH FROM information_schema.tables '
                       'WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME LIKE %s', ['core_kb%'])
        storage = [{'table': row[0], 'data_bytes':row[1], 'index_bytes':row[2]} for row in cursor.fetchall()]
    return {'passed': bool(examples) and not report.get('rejected'), 'projection': report,
        'counts': {model.__name__: model.objects.count() for model in (KBRecord, KBName, KBRelation, KBVersion)},
        'python_peak_bytes': peak, 'process_memory':memory_snapshot(), 'mysql_storage_estimates':storage,
        'seconds': round(time.monotonic() - start, 4),
        'lookup_ms': {'p50': statistics.median(latencies) if latencies else None,
                      'p95':sorted(latencies)[max(0, math.ceil(len(latencies)*.95)-1)] if latencies else None,
                      'max': max(latencies) if latencies else None, 'samples': len(latencies)},
        'examples': examples, 'integrity': integrity, 'no_model_training': True}


def pilot(catalog, root, manifest, *, state_database, maximum=100):
    """Reutiliza el catálogo ya presente y sus importadores; cero descargas."""
    from .literary_gutenberg import import_catalog
    from .literary_memory import coverage_snapshot, default_path
    if not state_database or Path(state_database).exists() or maximum != 100:
        raise ValueError('El primer lote requiere un ledger nuevo y exactamente 100 registros como máximo.')
    before = coverage_snapshot()
    import_report = import_catalog(catalog, state_database=state_database, memory_database=default_path(),
        max_records=maximum, max_scanned=10000, max_seconds=60, max_storage_mb=32, languages=('en',))
    report = project_and_audit(state_database, root, manifest, maximum=maximum)
    report.update(catalog_import=import_report, memory_before=before, memory_after=coverage_snapshot(),
                  download_requests=0, full_texts_downloaded=0)
    return report


def http_smoke(root, manifest):
    from .bibliographic_http_probe import run_probe
    report = run_probe()
    report['integrity'] = preserve_existing_rows(root, manifest)
    return report
