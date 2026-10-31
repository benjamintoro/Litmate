"""Lotes oficiales con el importador/ledger existente; no crea otro catálogo."""
import argparse
import getpass
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=['works','authors','project'],required=True)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--ledger',type=Path,default=Path('data/adquisicion/ol_20260930.sqlite3'))
    parser.add_argument('--folder',type=Path,default=Path('data/adquisicion/openlibrary'))
    parser.add_argument('--max-records',type=int,default=200)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists() or not 1<=args.max_records<=10000:
        parser.error('Usa salida nueva y lote de 1..10000 registros.')
    from iniciar_mysql_local import local_database_environment
    password=getpass.getpass('Contraseña MySQL local (oculta): ')
    with local_database_environment(password):
        password=None
        os.environ.setdefault('DJANGO_SETTINGS_MODULE','litmate_project.settings')
        import django
        django.setup()
        from django.db import connection
        from core.database_transfer import verify_backup
        from core.bibliographic_expansion import preserve_expansion_rows,resource_snapshot
        from core.bibliographic_repository import project_ledger,lookup_sources
        from core.literary_acquisition import import_openlibrary_dump,acquisition_stats,drain_projection,_connect
        from core.literary_memory import default_path,coverage_snapshot
        if connection.vendor!='mysql' or connection.settings_dict['HOST']!='127.0.0.1':
            raise ValueError('Sólo MySQL local explícito.')
        if shutil.disk_usage(Path.cwd()).free<15*1024**3:
            raise ValueError('insufficient_disk_margin')
        manifest=verify_backup(args.backup)
        preserve_expansion_rows(args.backup,manifest)
        before=resource_snapshot();start=time.monotonic()
        report={'stage':args.stage,'before':before,'memory_before':coverage_snapshot(),
                'ledger_before':acquisition_stats(args.ledger),'full_texts_imported':0,'llm_calls':0}
        if args.stage=='project':
            report['projection']=project_ledger(args.ledger,max_records=args.max_records,
                batch_size=25,max_seconds=120,max_storage_mb=256)
            report['memory_projection']=drain_projection(state_database=args.ledger,
                memory_database=default_path(),max_records=args.max_records,max_seconds=120)
        else:
            receipt=json.loads((args.folder/('ol_dump_'+args.stage+'_2026-09-30.txt.gz.verified.json')).read_text(encoding='utf8'))
            options={}
            if args.stage=='works':
                options['subjects']=('fiction','literature','history','poetry','essay','peru',
                                     'literatura','historia','manga','latin america')
            else:
                with _connect(args.ledger) as db:
                    keys=[row[0] for row in db.execute("SELECT DISTINCT target FROM acquisition_relations WHERE predicate='author'")]
                if not keys or len(keys)>25000:
                    raise ValueError('Importa antes hasta 25000 dependencias bibliográficas.')
                options['record_ids']=keys
            report['import']=import_openlibrary_dump(args.folder/receipt['name'],
                state_database=args.ledger,memory_database=default_path(),source_url=receipt['source_url'],
                expected_sha256=receipt['sha256'],max_records=args.max_records,max_scanned=50000000,
                max_seconds=900,max_storage_mb=128,**options)
        report.update(seconds=round(time.monotonic()-start,3),after=resource_snapshot(),
            memory_after=coverage_snapshot(),ledger_after=acquisition_stats(args.ledger),
            integrity=preserve_expansion_rows(args.backup,manifest))
        with _connect(args.ledger) as db:
            works=[json.loads(row[0]) for row in db.execute("SELECT record FROM acquisition_records WHERE kind='work'")]
            report['works_with_description_in_dump']=sum(bool(w.get('description_available')) for w in works)
            report['descriptions_persisted']=0
            report['sample_retrieval']=[{'title':w['title'],'sources':lookup_sources(w['title'])}
                                        for w in works[:8]]
        args.output.write_text(json.dumps(report,ensure_ascii=True,indent=2),encoding='utf8')
        print(json.dumps({k:report[k] for k in ['stage','seconds','ledger_after','works_with_description_in_dump',
                          'descriptions_persisted']}|{k:report[k] for k in ['import','projection'] if k in report}),flush=True)


if __name__=='__main__':
    main()
