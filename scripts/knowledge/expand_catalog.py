"""Expansión local, reanudable y acotada; no modifica configuración ni esquema."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import time


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--maximum', type=int, choices=(1000, 10000), required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--previous-report', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('La salida debe ser nueva.')
    if args.maximum == 10000:
        if not args.previous_report:
            raise ValueError('El lote 10000 requiere el informe aprobado de 1000.')
        previous = json.loads(args.previous_report.read_text(encoding='utf-8'))
        if (not previous.get('passed') or previous.get('source_links_valid') != 1000
                or previous.get('sql_after', 0)-previous.get('sql_before', 0) != 1000):
            raise ValueError('No se superaron los controles del lote anterior.')
    from iniciar_mysql_local import local_database_environment
    password = getpass.getpass('Contraseña MySQL local (oculta): ')
    with local_database_environment(password, development_http=True):
        password = None
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'litmate_project.settings')
        import django
        django.setup()
        from django.db import connection
        from core.database_transfer import verify_backup
        from core.bibliographic_expansion import (select_catalog, preserve_expansion_rows,
                                                 retrieval_audit, resource_snapshot, pending_memory_projection)
        from core.knowledge_models import KBRecord
        from core.literary_memory import _connection, default_path, coverage_snapshot
        if (connection.vendor != 'mysql' or connection.settings_dict['HOST'] != '127.0.0.1'
                or connection.settings_dict['NAME'] != 'litmate_db'):
            raise ValueError('Se requiere MySQL local.')
        manifest = verify_backup(args.backup)
        preserve_expansion_rows(args.backup, manifest)
        before = resource_snapshot()
        if before['free_disk_bytes'] < 10*1024**3:
            raise ValueError('Se requieren al menos 10 GiB libres.')
        digest = hashlib.sha256(args.catalog.read_bytes()).hexdigest()
        if args.selection.exists():
            selection = json.loads(args.selection.read_text(encoding='utf-8'))
            if selection['catalog_sha256'] != digest or selection['maximum'] != args.maximum:
                raise ValueError('La selección no corresponde al catálogo/lote.')
        else:
            pairs = set()
            with _connection() as db:
                if db:
                    pairs.update(tuple(row) for row in db.execute('SELECT title_key,author_key FROM memory_works'))
            excluded = set(KBRecord.objects.filter(provider='gutenberg').values_list('external_id', flat=True))
            selection = select_catalog(args.catalog, args.maximum, pairs, excluded)
            selection.update(catalog_sha256=digest, maximum=args.maximum)
            write_new(args.selection, selection)
        report = {'selection': {key: value for key, value in selection.items() if key != 'selected'},
                  'before': before, 'memory_before': coverage_snapshot(), 'executed': args.execute,
                  'download_requests': 0, 'full_texts_downloaded': 0}
        print(json.dumps({'selected': len(selection['selected']), 'profile': report['selection']}, ensure_ascii=True), flush=True)
        if args.execute:
            from core.literary_gutenberg import import_catalog
            from core.bibliographic_repository import project_ledger
            from core.bibliographic_http_probe import run_probe
            ids = [item['id'] for item in selection['selected']]
            report['sql_before'] = KBRecord.objects.count()
            report['imports'], report['projections'] = [], []
            for attempt in range(5):
                result = import_catalog(args.catalog, state_database=args.ledger, memory_database=default_path(),
                    selected_ids=ids, languages=(), max_records=args.maximum,
                    max_scanned=100000, max_seconds=180, max_storage_mb=256)
                report['imports'].append(result)
                print(json.dumps({'import_attempt': attempt+1, 'result': result}), flush=True)
                if result.get('complete') and pending_memory_projection(args.ledger) == 0:
                    break
                if result.get('storage_limit'):
                    raise ValueError('Cuota de ledger alcanzada.')
            if not result.get('complete') or pending_memory_projection(args.ledger):
                raise ValueError('Importación aún incompleta; reanudar desde selección fija.')
            for attempt in range(60):
                result = project_ledger(args.ledger, max_records=250, batch_size=25,
                                        max_seconds=20, max_storage_mb=256)
                report['projections'].append(result)
                if any(result.get(key) for key in ('rejected', 'conflicts')):
                    raise ValueError('Proyección requiere revisión; no continuar.')
                if attempt % 4 == 0 or result.get('complete'):
                    print(json.dumps({'projection_attempt': attempt+1, 'result': result}), flush=True)
                if result.get('complete'):
                    break
                if resource_snapshot()['free_disk_bytes'] < 10*1024**3:
                    raise ValueError('Margen de disco agotado.')
                time.sleep(.1)
            else:
                raise ValueError('Proyección incompleta: reanudar.')
            records = list(KBRecord.objects.filter(provider='gutenberg', external_id__in=ids))
            if len(records) != len(ids) or any(record.status != 'source_metadata' for record in records):
                raise ValueError('Faltan registros admitidos en MySQL.')
            if any(record.source_url != 'https://www.gutenberg.org/ebooks/'+record.external_id
                   or record.verified_at is not None for record in records):
                raise ValueError('Procedencia o nivel de verificación inválidos.')
            report['source_links_valid'] = len(records)
            report['quality'] = {
                'identifiable_provider_ids': len(records),
                'catalog_author_labels': sum(bool(record.payload.get('author')) for record in records),
                'independently_verified_authorship': 0,
                'admitted_synopses': 0, 'character_information': 0,
                'metadata_only_not_full_text_permission': True,
                'human_verified_records': sum(record.verified_at is not None for record in records)}
            report['sql_after'] = KBRecord.objects.count()
            report['retrieval'] = retrieval_audit(selection['selected'])
            report['http'] = run_probe(record_ids=[record.id for record in records])
            report['integrity'] = preserve_expansion_rows(args.backup, manifest)
            report['memory_after'] = coverage_snapshot()
            report['after'] = resource_snapshot()
            report['ledger_bytes'] = args.ledger.stat().st_size
            report['pending_memory_projection'] = pending_memory_projection(args.ledger)
            report['passed'] = (report['http']['passed'] and report['retrieval']['wrong'] == 0
                and report['retrieval']['correct'] >= report['retrieval']['samples']*.8
                and report['retrieval']['p95_ms'] < 500)
        write_new(args.output, report)
        print(json.dumps({key: value for key, value in report.items() if key in
            {'passed','sql_before','sql_after','source_links_valid','after','ledger_bytes'}}, ensure_ascii=True), flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'passed': False, 'error_class': type(error).__name__, 'reason': str(error)}), flush=True)
        raise SystemExit(1)
