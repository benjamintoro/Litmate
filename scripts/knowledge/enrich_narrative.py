"""Piloto reanudable de profundidad narrativa: sólo obras YA presentes en memoria."""
import argparse
import getpass
import json
import os
from pathlib import Path
import time
from .expand_catalog import write_new

# Selección de evaluación, nunca excepciones en los mecanismos de recuperación.
PILOT_TITLES = ('Orgullo y prejuicio','Dune','Don Quijote','El principito',
    'Diario secreto de Papelucho y el marciano','Rayuela','Frankenstein','Historia de Chile',
    'Nana','Emma','Dracula','Little Women','Siddhartha','Agua de Nieve',
    'The Time Machine','The Wonderful Wizard of Oz','Moby-Dick; or, The Whale')


def select_existing(database, maximum=100):
    from core.literary_identity import normalize_identity
    from core.literary_memory import _connection
    wanted = {normalize_identity(title):index for index,title in enumerate(PILOT_TITLES)}
    selected = []
    with _connection(database) as db:
        for row in db.execute('SELECT record FROM memory_works'):
            work = json.loads(row[0])
            if normalize_identity(work['title']) in wanted:
                selected.append(work)
    # Mantiene homónimos como candidatos distintos, sin fusionar autores.
    return sorted(selected, key=lambda work:(wanted[normalize_identity(work['title'])],work['author']))[:maximum]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--rounds', type=int, default=4)
    parser.add_argument('--work-id', action='append', default=[],
                        help='ID existente; repetible, hasta 100 obras. No añade títulos.')
    parser.add_argument('--wikidata-only', action='store_true',
                        help='Busca pertenencia de personajes CC0; no inventa sus roles.')
    args = parser.parse_args()
    if args.output.exists() or not 1 <= args.rounds <= 10:
        raise ValueError('Usa una salida nueva y 1..10 lotes acotados.')
    from iniciar_mysql_local import local_database_environment
    password = getpass.getpass('Contraseña MySQL local (oculta): ')
    with local_database_environment(password, development_http=True):
        password = None
        os.environ.setdefault('DJANGO_SETTINGS_MODULE','litmate_project.settings')
        import django
        django.setup()
        from django.db import connection
        from core.database_transfer import verify_backup
        from core.bibliographic_operations import preserve_existing_rows
        from core.bibliographic_expansion import resource_snapshot
        from core.literary_memory import (default_path, get_work, enqueue_refresh, coverage_snapshot,
                                         _connection)
        from core.literary_enrichment import narrative_coverage
        from core.literary_learning import run_refresh_batch, lower_worker_priority
        if connection.vendor != 'mysql' or connection.settings_dict['HOST'] != '127.0.0.1':
            raise ValueError('Se requiere MySQL local.')
        manifest = verify_backup(args.backup)
        preserve_existing_rows(args.backup, manifest)
        database = default_path()
        if args.plan.exists():
            plan = json.loads(args.plan.read_text(encoding='utf-8'))
        else:
            selected = ([get_work(wid,database=database) for wid in dict.fromkeys(args.work_id)]
                        if args.work_id else select_existing(database))
            if not selected or len(selected) > 100 or any(work is None for work in selected):
                raise ValueError('Selecciona 1..100 IDs existentes.')
            ids = [work['work_id'] for work in selected]
            plan = {'selected':selected,'coverage_before':coverage_snapshot(),
                    'narrative_before':narrative_coverage(database),
                    'pilot_before':narrative_coverage(database, ids),
                    'resources_before':resource_snapshot(),
                    'manga_present_in_selected_stores':False,
                    'manga_limit':'Sin manga localizado en inventario; no se añaden títulos nuevos.'}
            write_new(args.plan, plan)
        selected = plan['selected']
        ids = [work['work_id'] for work in selected]
        if not ids or len(ids) > 100 or any(get_work(wid, database=database) is None for wid in ids):
            raise ValueError('El plan requiere 1..100 obras existentes.')
        report = {'selected':selected,'executed':args.execute,'batches':[],
            'coverage_before':plan['coverage_before'],'narrative_before':plan['narrative_before'],
            'pilot_before':plan['pilot_before'],'new_titles_imported':0,'llm_calls':0}
        if args.execute:
            lower_worker_priority()
            current = narrative_coverage(database, ids)['per_work']
            for work in selected:
                detail = current[work['work_id']]
                for requirement, missing in (('summary',not detail['synopsis']),('characters',not detail['roles'])):
                    if args.wikidata_only and requirement != 'characters':
                        continue
                    if missing:
                        enqueue_refresh(work['work_id'], requirement, 'wikidata' if args.wikidata_only else 'wikipedia',
                                        priority=90 if args.wikidata_only else 100, database=database)
            log = args.output.with_suffix('.jsonl')
            if log.exists():
                raise ValueError('El historial del lote ya existe; usa otra salida.')
            for turn in range(args.rounds):
                if resource_snapshot()['free_disk_bytes'] < 10*1024**3:
                    raise ValueError('Margen de disco insuficiente.')
                batch = run_refresh_batch(database=database, max_jobs=20, max_seconds=120,
                    job_seconds=12,pause_seconds=2 if args.wikidata_only else 1,narrative_pages=1,work_ids=ids)
                report['batches'].append(batch)
                with log.open('a',encoding='utf-8') as stream:
                    stream.write(json.dumps(batch,ensure_ascii=False)+'\n')
                print(json.dumps({'round':turn+1, **{key:batch[key] for key in
                    ('claimed','completed','deferred','stored','seconds')}},ensure_ascii=True),flush=True)
                if not batch['claimed']:
                    break
        report.update(coverage_after=coverage_snapshot(), narrative_after=narrative_coverage(database),
            pilot_after=narrative_coverage(database, ids), resources_after=resource_snapshot(),
            integrity=preserve_existing_rows(args.backup,manifest))
        if report['coverage_after']['works_catalogued'] != plan['coverage_before']['works_catalogued']:
            raise ValueError('Cambió el número de títulos; revisar antes de continuar.')
        with _connection(database) as db:
            report['jobs'] = [dict(row) for row in db.execute('SELECT work_id,requirement,provider,status,attempts,last_error '
                'FROM memory_jobs WHERE work_id IN ('+','.join('?' for _ in ids)+')',ids)]
        write_new(args.output,report)
        print(json.dumps({'new_titles_imported':0,'narrative_after':{key:value for key,value in report['narrative_after'].items()
            if key!='per_work'},'work_count':report['coverage_after']['works_catalogued']},ensure_ascii=True),flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'passed':False,'error_class':type(error).__name__}),flush=True)
        raise SystemExit(1)
