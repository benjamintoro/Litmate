"""Auditoría narrativa antes/después; usa snapshots originales y consultas reales."""
import argparse
import getpass
import json
import os
from pathlib import Path
import statistics
import time
import sqlite3
from contextlib import closing
from .expand_catalog import write_new


def preserve_narrative_memory(original,current):
    """Admite sólo enlaces nuevos; conserva identidades y evidencia anterior."""
    result={}
    with closing(sqlite3.connect(Path(original).resolve().as_uri()+'?mode=ro',uri=True)) as before, \
         closing(sqlite3.connect(Path(current).resolve().as_uri()+'?mode=ro',uri=True)) as after:
        for table in ('memory_works','memory_sources','memory_entities','memory_assertions','memory_conflicts'):
            info=before.execute('PRAGMA table_info('+table+')').fetchall()
            if not info:continue
            key=next(i for i,c in enumerate(info) if c[5]==1)
            columns=[c[1] for c in info]
            old=before.execute('SELECT * FROM '+table).fetchall()
            actual={row[key]:row for row in after.execute('SELECT * FROM '+table)}
            enriched=[]
            for row in old:
                new=actual.get(row[key])
                if new is None:raise ValueError('Falta una fila original: '+table)
                if new==row:continue
                if table not in {'memory_works','memory_entities'}:
                    raise ValueError('Cambió evidencia original: '+table)
                index=columns.index('record')
                if any(left!=right for i,(left,right) in enumerate(zip(row,new)) if i!=index):
                    raise ValueError('Cambió una identidad original.')
                prior,now=json.loads(row[index]),json.loads(new[index])
                for field,value in prior.items():
                    if not value:continue
                    if field in {'url','source'} and table=='memory_works':continue
                    if isinstance(value,list):
                        if any(item not in now.get(field,[]) for item in value):
                            raise ValueError('Se perdió metadato anterior.')
                    elif now.get(field)!=value:raise ValueError('Cambió un hecho anterior.')
                if table=='memory_works' and (prior.get('url')!=now.get('url') or prior.get('source')!=now.get('source')):
                    if not after.execute('SELECT 1 FROM memory_sources WHERE work_id=? AND url=?',
                        (row[key],now.get('url'))).fetchone():
                        raise ValueError('Nueva procedencia sin fuente admitida.')
                enriched.append(row[key])
            result[table]={'original_rows':len(old),'after':len(actual),'preserved':True,
                           'enriched_metadata_records':len(enriched),'enriched_ids':enriched}
        if after.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Memoria dañada.')
    return result


def probes(works, database):
    from core.literary_memory import retrieve_evidence
    from core.literary_ai import canonical_sources
    from core.ai_narrative_answers import request_for, direct_answer
    examples=[]
    for work in works:
        for requirement, prefix in [('summary','Dime la trama de '),('characters','Dime los personajes de ')]:
            message=prefix+work['title']
            started=time.monotonic()
            books,sources=retrieve_evidence(work['title'],books=[work],requirement=requirement,database=database,limit=12)
            elapsed=(time.monotonic()-started)*1000
            result=direct_answer(message,request_for(message),canonical_sources([*books,*sources],20))
            examples.append({'title':work['title'],'work_id':work['work_id'],'requirement':requirement,
                'answered':bool(result and result.status=='answered'),'answer':result.text if result else None,
                'retrieval_ms':elapsed,'stored_sources':len(sources),'llm_calls':0})
    values=sorted(item['retrieval_ms'] for item in examples)
    return {'examples':examples,'answered':sum(item['answered'] for item in examples),'queries':len(examples),
            'p50_ms':statistics.median(values),'p95_ms':values[max(0,int(len(values)*.95+.999)-1)]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--http',action='store_true')
    args=parser.parse_args()
    if args.output.exists():
        raise ValueError('Elige una salida nueva.')
    from iniciar_mysql_local import local_database_environment
    password=getpass.getpass('Contraseña MySQL local (oculta): ')
    with local_database_environment(password,development_http=True):
        password=None
        os.environ.setdefault('DJANGO_SETTINGS_MODULE','litmate_project.settings')
        import django;django.setup()
        from django.conf import settings
        from core.database_transfer import verify_backup
        from core.bibliographic_operations import preserve_existing_rows
        from core.literary_enrichment import narrative_coverage
        from core.literary_memory import default_path,coverage_snapshot,_connection
        from core.bibliographic_expansion import resource_snapshot
        from core.knowledge_models import KBRecord
        from core.models import Libro
        from core.literary_memory_rag import build_memory_index,search_memory_semantic
        manifest=verify_backup(args.backup)
        original=args.backup/'files'/'data'/'literary_memory.sqlite3'
        database=default_path()
        selected=json.loads(args.plan.read_text(encoding='utf-8'))['selected']
        ids=[work['work_id'] for work in selected]
        before,after=narrative_coverage(original),narrative_coverage(database)
        report={'before':before,'after':after,'pilot_before':narrative_coverage(original,ids),
            'pilot_after':narrative_coverage(database,ids),'coverage':coverage_snapshot(),
            'mysql_integrity':preserve_existing_rows(args.backup,manifest),
            'memory_integrity':preserve_narrative_memory(original,database),
            'queries_before':probes(selected,original),'queries_after':probes(selected,database),
            'stores':{'mysql_structured_records':KBRecord.objects.count(),
                'mysql_legacy_books':Libro.objects.count(),
                'legacy_nonempty_synopsis_not_rights_verified':Libro.objects.exclude(sinopsis='').count(),
                'mysql_narrative_tables_added':0,'sqlite_memory':str(database)},
            'external_calls_in_audit':0,'new_titles_imported':0}
        index=args.output.with_suffix('.sqlite3')
        report['rag']=build_memory_index(database=database,index=index,work_ids=ids,max_seconds=60)
        report['rag_queries']=[]
        for work in selected:
            if not report['pilot_after']['per_work'][work['work_id']]['synopsis']:
                continue
            started=time.monotonic()
            books,sources=search_memory_semantic('argumento trama',books=[work],database=database,index=index)
            report['rag_queries'].append({'title':work['title'],'retrieved':bool(sources),
                'sources':[source['memory_source_id'] for source in sources],
                'milliseconds':(time.monotonic()-started)*1000})
        with _connection(database) as db:
            report['sources']=[json.loads(row[0]) for row in db.execute(
                "SELECT record FROM memory_sources WHERE json_extract(record,'$.evidence_scope') IS NOT NULL")]
            report['character_assertions']=db.execute("SELECT COUNT(*) FROM memory_assertions WHERE topic='characters'").fetchone()[0]
        if args.http:
            from core.bibliographic_http_probe import run_probe
            report['http']=[run_probe(question='Dime la trama de Orgullo y prejuicio',
                require_sql_card=False,must_contain=('Bennet',)),
                run_probe(question='¿Quién es el protagonista de Orgullo y prejuicio?',
                require_sql_card=False,must_contain=('Elizabeth',))]
        report['resources']=resource_snapshot()
        report['passed']=(before['works']==after['works'] and after['works_with_explicit_plot']>before['works_with_explicit_plot']
            and report['rag']['index_updated'] and all(item['passed'] for item in report.get('http',[])))
        write_new(args.output,report)
        print(json.dumps({'passed':report['passed'],'before':{k:v for k,v in before.items() if k!='per_work'},
            'after':{k:v for k,v in after.items() if k!='per_work'},
            'local_queries_answered':[report['queries_before']['answered'],report['queries_after']['answered']],
            'http':[{'passed':item['passed'],'seconds':item['seconds'],'status':item['status']} for item in report.get('http',[])]},ensure_ascii=True))


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'passed':False,'error_class':type(error).__name__,'reason':str(error)}),flush=True)
        raise SystemExit(1)
