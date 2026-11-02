"""Auditoría final de lotes ya importados; sin volver a importar ni crear lectores."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing
from .expand_catalog import write_new


def memory_integrity(original, current):
    """Compara todas las entidades/fuentes originales por PK, admite adiciones."""
    result = {}
    with closing(sqlite3.connect(Path(original).resolve().as_uri()+'?mode=ro', uri=True)) as before, \
         closing(sqlite3.connect(Path(current).resolve().as_uri()+'?mode=ro', uri=True)) as after:
        for table in ('memory_works','memory_sources','memory_entities','memory_assertions','memory_conflicts'):
            info = before.execute('PRAGMA table_info('+table+')').fetchall()
            if not info:
                continue
            key = next(index for index, column in enumerate(info) if column[5] == 1)
            old = before.execute('SELECT * FROM '+table).fetchall()
            actual = {row[key]: row for row in after.execute('SELECT * FROM '+table)}
            missing = sum(row[key] not in actual for row in old)
            changed = refreshed = 0
            for row in old:
                if row[key] not in actual or actual[row[key]] == row:
                    continue
                current = actual[row[key]]
                differences = [i for i in range(len(row)) if row[i] != current[i]]
                # La investigación existente renueva vigencia al consultar una
                # fuente idéntica. Nunca admite cambios a hash, URL o contenido.
                if table == 'memory_sources' and all(info[i][1] in
                        {'retrieved_at','verified_at','expires_at'} and row[i] is not None
                        and current[i] is not None and current[i] >= row[i] for i in differences):
                    refreshed += 1
                else:
                    changed += 1
            result[table] = {'before': len(old), 'after': len(actual), 'missing': missing,
                             'changed': changed, 'unchanged_content_validity_refreshed': refreshed}
        if after.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Falló quick_check de la memoria.')
    if any(row['missing'] or row['changed'] for row in result.values()):
        raise ValueError('Cambió conocimiento original; revisar antes de continuar.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--selections', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('La salida debe ser nueva.')
    from iniciar_mysql_local import local_database_environment
    password = getpass.getpass('Contraseña MySQL local (oculta): ')
    with local_database_environment(password, development_http=True):
        password = None
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'litmate_project.settings')
        import django
        django.setup()
        from core.database_transfer import verify_backup
        from core.bibliographic_expansion import preserve_expansion_rows, retrieval_audit, resource_snapshot
        from core.literary_memory import default_path, coverage_snapshot
        from core.knowledge_models import KBRecord, KBName, KBVersion, KBRelation
        from core.bibliographic_http_probe import run_probe
        manifest = verify_backup(args.backup)
        report = {'integrity': preserve_expansion_rows(args.backup, manifest),
            'memory_integrity': memory_integrity(args.backup/'files'/'data'/'literary_memory.sqlite3', default_path()),
            'coverage': coverage_snapshot(), 'resources': resource_snapshot(),
            'counts': {model.__name__:model.objects.count() for model in (KBRecord,KBName,KBVersion,KBRelation)},
            'batches': []}
        for selection_path in args.selections:
            selection = json.loads(selection_path.read_text(encoding='utf-8'))
            items = selection['selected']
            records = list(KBRecord.objects.filter(provider='gutenberg', external_id__in=[item['id'] for item in items]))
            if len(records) != len(items):
                raise ValueError('No se recuperaron todos los IDs del lote.')
            report['batches'].append({'selection': str(selection_path), 'actual_records': len(records),
                'catalog_author_labels': sum(bool(record.payload.get('author')) for record in records),
                'source_links_valid': sum(record.source_url == 'https://www.gutenberg.org/ebooks/'+record.external_id
                                          for record in records),
                'human_verified': sum(record.verified_at is not None for record in records),
                'retrieval': retrieval_audit(items), 'http':run_probe(record_ids=[record.id for record in records])})
        report['passed'] = all(batch['retrieval']['wrong'] == 0 and batch['http']['passed']
            and batch['source_links_valid'] == batch['actual_records'] for batch in report['batches'])
        write_new(args.output, report)
        print(json.dumps({'passed':report['passed'], 'counts':report['counts'],
            'batches':[{k:v for k,v in batch.items() if k not in {'retrieval','http'}} for batch in report['batches']]}))


if __name__ == '__main__':
    main()
