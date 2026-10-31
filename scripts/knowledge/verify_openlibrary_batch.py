"""Verificación local de proyección, fuentes y respaldo; no importa datos."""
import argparse
from contextlib import closing
import getpass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time


def assertion_preserved_in_snapshot(assertion,source):
    """Una afirmación sustituida necesita su hecho y pasaje originales exactos."""
    fact=json.loads(assertion['record'])
    evidence=fact.get('evidence','')
    return (source.get('work_id')==assertion['work_id'] and fact in source.get('literary_facts',[])
            and bool(evidence) and any(evidence in str(source.get(k,''))
                                     for k in ('description','narrative_context')))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--ledger',type=Path,default=Path('data/adquisicion/ol_20260930.sqlite3'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--final-backup',type=Path)
    args=parser.parse_args()
    if args.output.exists() or (args.final_backup and args.final_backup.exists()):
        parser.error('Usa rutas nuevas para informes y respaldos.')
    from iniciar_mysql_local import local_database_environment
    password=getpass.getpass('Contraseña MySQL local (oculta): ')
    with local_database_environment(password):
        password=None
        os.environ.setdefault('DJANGO_SETTINGS_MODULE','litmate_project.settings')
        import django
        django.setup()
        from django.conf import settings
        from django.db import connection
        from core.database_transfer import verify_backup,create_backup
        from core.bibliographic_expansion import preserve_expansion_rows,resource_snapshot,retrieval_audit
        from core.literary_acquisition import _connect,_stored,_book_projection,acquisition_stats,local_openlibrary_detail
        from core.literary_memory import default_path,coverage_snapshot
        if connection.vendor!='mysql' or connection.settings_dict['HOST']!='127.0.0.1':
            raise ValueError('Sólo verificación explícita de MySQL local.')
        started=time.monotonic()
        manifest=verify_backup(args.backup)
        report={'sql_integrity':preserve_expansion_rows(args.backup,manifest),
                'resources':resource_snapshot(),'ledger':acquisition_stats(args.ledger),
                'memory_coverage':coverage_snapshot()}
        records=[]
        with closing(_connect(args.ledger)) as db:
            raw=list(db.execute("SELECT external_id,record FROM acquisition_records WHERE kind='work'"))
            for row in raw:
                record=_stored(db,'openlibrary',row['external_id'])
                projected=_book_projection(db,record)
                if projected:
                    source=projected[0]
                    records.append({'id':record['external_id'],'title':source['title'],'author':source['author']})
            report['descriptions_in_dump']=sum(bool(json.loads(row['record']).get('description_available')) for row in raw)
            described=[row['external_id'] for row in raw if json.loads(row['record']).get('description_available')
                       and 'raw_offset' in json.loads(row['record']).get('provenance',{})]
        report['resolved_works']=len(records)
        report['retrieval']=retrieval_audit(records,sample_size=120)
        report['description_pointer_sample']=[{'id':key,'available':bool(local_openlibrary_detail(key))}
                                               for key in described[:12]]
        # Las actualizaciones legítimas conservan el texto anterior en el
        # historial. Se exige el registro original exacto, no sólo su título.
        original=args.backup/'files'/'data'/'literary_memory.sqlite3'
        def read_only(path):
            db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
            db.row_factory=sqlite3.Row
            return db
        with closing(read_only(original)) as old,closing(read_only(default_path())) as current:
            preserved=archived=missing=0
            for row in old.execute('SELECT * FROM memory_sources'):
                match=current.execute('SELECT * FROM memory_sources WHERE source_id=?',(row['source_id'],)).fetchone()
                if match and all(match[k]==row[k] for k in ('work_id','content_hash','record')):
                    preserved+=1
                elif current.execute('SELECT 1 FROM memory_history WHERE source_id=? AND content_hash=? AND record=?',
                        (row['source_id'],row['content_hash'],row['record'])).fetchone():
                    archived+=1
                else:
                    missing+=1
            report['original_memory_sources']={'preserved':preserved,'archived_exactly':archived,'missing':missing}
            if missing:
                raise ValueError('Fuente original sin conservación verificable.')
            missing_assertions=archived_assertions=0
            for row in old.execute('SELECT * FROM memory_assertions'):
                match=current.execute('SELECT * FROM memory_assertions WHERE assertion_id=?',(row['assertion_id'],)).fetchone()
                if not match or tuple(match)!=tuple(row):
                    source=old.execute('SELECT * FROM memory_sources WHERE source_id=?',(row['source_id'],)).fetchone()
                    history=(current.execute('SELECT record FROM memory_history WHERE source_id=? AND content_hash=? AND record=?',
                        (row['source_id'],source['content_hash'],source['record'])).fetchone() if source else None)
                    if history and assertion_preserved_in_snapshot(row,json.loads(history['record'])):
                        archived_assertions+=1
                    else:
                        missing_assertions+=1
            report['original_assertions']={'superseded_and_archived_exactly':archived_assertions,
                                          'changed_or_missing_without_archive':missing_assertions}
            if missing_assertions:
                raise ValueError('Afirmaciones originales modificadas; inspecciona antes de continuar.')
        stores={Path(getattr(settings,k)) for k in dir(settings) if k.startswith('LITMATE_') and k.endswith('_DB')}
        report['sqlite_integrity']={}
        for path in sorted(stores):
            if not path.is_file():
                continue
            with closing(read_only(path)) as db:
                check=db.execute('PRAGMA quick_check').fetchall()
            result=[row[0] for row in check]
            report['sqlite_integrity'][str(path.relative_to(settings.BASE_DIR))]=result
            if result!=['ok']:
                raise ValueError('SQLite no íntegro: '+path.name)
        report['env_unchanged']=hashlib.sha256(Path('.env').read_bytes()).hexdigest()==(
            '1d8e35effc765d26ecb73f3e2ee26c886a1e3d98b1bc45590c356b8604008e74')
        if not report['env_unchanged']:
            raise ValueError('.env cambió desde el inicio; no publicar configuración.')
        report['seconds']=round(time.monotonic()-started,3)
        if args.final_backup:
            backup=create_backup(args.final_backup)
            report['final_backup']={'path':str(args.final_backup),'verified':True,
                'tables':len(backup['database']['tables']),
                'rows':sum(t['count'] for t in backup['database']['tables'].values()),
                'files':len(backup['files'])}
        args.output.write_text(json.dumps(report,ensure_ascii=True,indent=2),encoding='utf8')
        print(json.dumps({k:report[k] for k in ('resolved_works','descriptions_in_dump','original_memory_sources',
              'original_assertions','env_unchanged','seconds')} |
              {'retrieval':{k:v for k,v in report['retrieval'].items() if k!='examples'},
               'final_backup':report.get('final_backup')}),flush=True)


if __name__=='__main__':
    main()
