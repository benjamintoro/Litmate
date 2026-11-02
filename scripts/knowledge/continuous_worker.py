"""Un lote local MySQL, contraseña oculta, sin editar .env ni registrar tareas."""
import argparse
import getpass
import gzip
import json
import os
from pathlib import Path
import sys


def checkpoint_rows_for_comparison(original, actual, columns):
    """Allow only the existing worker's derived progress to advance.

    Book, source and relation rows remain byte-for-byte comparable. Lease
    fields and every other projection checkpoint retain the original check.
    """
    from core.bibliographic_repository import digest
    key = columns.index('id')
    before = next((row for row in original if row[key] == digest('continuous-enrichment-v1')), None)
    result = []
    for row in actual:
        copy = list(row)
        if before is not None and row[key] == before[key]:
            position = columns.index('last_rowid')
            if row[position] < before[position]:
                raise ValueError('El checkpoint no puede retroceder.')
            counters = row[columns.index('counters')]
            counters = json.loads(counters) if isinstance(counters,str) else counters
            if (not isinstance(counters,dict) or set(counters) != {'works_selected','completed','sources_stored'}
                    or any(type(value) is not int or value < 0 for value in counters.values())
                    or counters['works_selected'] > 25 or counters['completed'] > 20):
                raise ValueError('Contadores de checkpoint inválidos.')
            for field in ('last_rowid','counters','updated_at'):
                position = columns.index(field)
                copy[position] = before[position]
        result.append(copy)
    return result


def verify_additive_sql(root, manifest):
    """All original rows/keys unchanged; only new evidence/control rows allowed."""
    from django.db import connection
    from core.database_transfer import decode, table_rows, fingerprint
    result = {}
    for table, info in manifest['database']['tables'].items():
        with gzip.open(root/'database'/info['file'], 'rt', encoding='utf-8') as stream:
            original = [[decode(value) for value in json.loads(line)] for line in stream]
        actual = table_rows(connection, table)
        columns, pk = info['columns'], info['pk']
        if pk:
            index = columns.index(pk)
            keys = {row[index] for row in original}
            previous = [row for row in actual if row[index] in keys]
        else:
            previous = actual
        checkpoint_updated = False
        if table == 'core_kbprojection':
            comparable = checkpoint_rows_for_comparison(original,previous,columns)
            checkpoint_updated = comparable != previous
        else:
            comparable = previous
        measured = fingerprint(table, columns, comparable, pk)
        if any(measured[key] != info[key] for key in measured):
            raise ValueError('Cambió una fila original: '+table)
        added = len(actual)-len(original)
        if added and table not in {'core_kbrelation', 'core_kbprojection'}:
            raise ValueError('Adición fuera del piloto: '+table)
        result[table] = {'original_rows_preserved': len(original), 'added': added}
        if checkpoint_updated:
            result[table]['derived_worker_checkpoint_updated'] = True
    connection.check_constraints()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--max-works', type=int, default=5)
    parser.add_argument('--work-id', action='append', default=[])
    parser.add_argument('--requirement', action='append', default=[],
                        help='Requisito público, por ejemplo main_characters; hasta seis por lote.')
    parser.add_argument('--max-jobs', type=int, default=2)
    parser.add_argument('--max-seconds', type=float, default=30)
    parser.add_argument('--job-seconds', type=float, default=8)
    parser.add_argument('--pause', type=float, default=2)
    parser.add_argument('--stop-file', type=Path)
    parser.add_argument('--non-interactive', action='store_true')
    parser.add_argument('--pilot-backup', type=Path, help='Verifica respaldo y compara todas las filas SQL originales.')
    parser.add_argument('--verify-only', action='store_true', help='Lee cobertura en proceso nuevo, sin red ni escrituras.')
    args = parser.parse_args(argv)
    from datetime import datetime
    output = args.output or Path('reports/continuous_runs')/(datetime.now().strftime('%Y%m%dT%H%M%S')+'.json')
    if output.exists():
        parser.error('Usa una salida nueva; se conservan los informes anteriores.')
    password = os.environ.pop('LITMATE_MYSQL_PASSWORD', '')
    if not password and not args.non_interactive:
        password = getpass.getpass('Contraseña MySQL local (oculta): ')
    if not password:
        raise ValueError('Falta contraseña local. No se ejecutó el lote.')
    from iniciar_mysql_local import local_database_environment
    with local_database_environment(password):
        password = None
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'litmate_project.settings')
        import django
        django.setup()
        from django.db import connection
        from core.literary_memory import default_path, get_work, _connection, retrieve_evidence
        from core.literary_enrichment import narrative_coverage
        from core.continuous_knowledge import run_continuous_batch
        from .expand_catalog import write_new
        if connection.vendor != 'mysql' or connection.settings_dict['HOST'] != '127.0.0.1':
            raise ValueError('El trabajador requiere MySQL local explícito.')
        database = default_path()
        manifest = None
        if args.pilot_backup:
            from core.database_transfer import verify_backup
            manifest = verify_backup(args.pilot_backup)
            verify_additive_sql(args.pilot_backup, manifest)
        if args.pilot_backup and not args.work_id:
            raise ValueError('Un piloto requiere IDs públicos explícitos, máximo 25.')
        if args.verify_only and not args.work_id:
            raise ValueError('La comprobación requiere al menos un ID existente.')
        works = [get_work(identifier, database=database) for identifier in dict.fromkeys(args.work_id)]
        if len(works) > 25 or any(work is None for work in works):
            raise ValueError('Selecciona hasta 25 obras existentes.')
        ids = [work['work_id'] for work in works]
        before = narrative_coverage(database, ids) if ids else None
        if args.verify_only:
            result = {'read_only': True, 'network': False, 'coverage': before, 'retrieval': []}
            from core.literary_identity import ambiguous_work_page
            from core.literary_memory import get_current_source
            from core.literary_memory_rag import search_memory_semantic
            with _connection(database) as db:
                result['sqlite_integrity'] = db.execute('PRAGMA integrity_check').fetchone()[0]
                result['sqlite_foreign_key_errors'] = len(db.execute('PRAGMA foreign_key_check').fetchall())
                result['queue_counts'] = dict(db.execute('SELECT status,COUNT(*) FROM memory_jobs GROUP BY status'))
                quarantined = [row['source_id'] for row in db.execute('SELECT source_id,record FROM memory_sources')
                    if ambiguous_work_page(json.loads(row['record']))]
                result['quarantined_disambiguation_snapshots'] = quarantined
            result['quarantine_enforced'] = all(get_current_source(sid, database=database) is None for sid in quarantined)
            with connection.cursor() as cursor:
                tables = connection.introspection.table_names(cursor)
                result['mysql_row_counts'] = {}
                for table in tables:
                    cursor.execute('SELECT COUNT(*) FROM '+connection.ops.quote_name(table))
                    result['mysql_row_counts'][table] = cursor.fetchone()[0]
            for work in works:
                books, sources = retrieve_evidence(work['title'], books=[work], requirement='characters', database=database)
                unused, indexed = search_memory_semantic(work['title'], books=[work], database=database,
                    index=database.with_name(database.stem+'_rag.sqlite3'))
                result['retrieval'].append({'work_id': work['work_id'], 'sources': len(sources),
                    'verified_sources': sum(source.get('memory_verified') is True for source in sources),
                    'rag_rehydrated_sources': len(indexed), 'facts': [
                        {'source_url': source['url'], 'source_id': source.get('memory_source_id'),
                         'license': source.get('license'), 'attribution': source.get('attribution'),
                         'roles': source.get('character_facts', [])} for source in sources if source.get('character_facts')]})
        else:
            result = run_continuous_batch(database=database, maximum=args.max_works, work_ids=ids,
                max_jobs=args.max_jobs, max_seconds=args.max_seconds, job_seconds=args.job_seconds,
                pause_seconds=args.pause, stop_file=args.stop_file, project_mysql=True,
                requirements=tuple(args.requirement) if args.requirement else ('summary','characters'))
            result['coverage_before'] = before
            result['coverage_after'] = narrative_coverage(database, ids) if ids else None
        result['database'] = {'vendor': connection.vendor, 'name': connection.settings_dict['NAME']}
        if ids:
            with _connection(database) as db:
                result['jobs'] = [dict(row) for row in db.execute(
                    'SELECT work_id,requirement,provider,status,attempts,last_error,not_before,payload '
                    'FROM memory_jobs WHERE work_id IN ('+','.join('?' for unused in ids)+')', ids)]
        if manifest:
            result['original_sql_rows'] = verify_additive_sql(args.pilot_backup, manifest)
        write_new(output, result)
        print(json.dumps({key: value for key, value in result.items() if key in (
            'mode', 'stopped', 'seconds', 'cpu_seconds', 'process', 'storage_delta_bytes', 'batch',
            'mysql_references_added', 'mysql_projection_error', 'index', 'read_only', 'database')}, ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Never log a connection exception containing a DSN/password.
        print(json.dumps({'passed': False, 'error_class': type(error).__name__}), file=sys.stderr)
        raise SystemExit(1)
