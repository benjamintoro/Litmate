"""Read-only SQL/memory/RAG inventory for a bounded public evaluation corpus."""
import argparse
import getpass
import json
import os
from pathlib import Path

CASES=(('Drácula','Bram Stoker'),('Siddhartha','Hermann Hesse'),
       ('Frankenstein','Mary Shelley'),('La Odisea','Homero'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--catalogue-inventory', action='store_true',
                        help='Cuenta carencias de metadatos SQL sin almacenar filas ni textos.')
    args=parser.parse_args()
    if args.output.exists():
        parser.error('Use a new report filename.')
    from iniciar_mysql_local import local_database_environment
    password=getpass.getpass('Contraseña MySQL local (oculta): ')
    with local_database_environment(password):
        password=None
        os.environ.setdefault('DJANGO_SETTINGS_MODULE','litmate_project.settings')
        import django
        django.setup()
        from django.db import connection
        from core.knowledge_models import KBRecord
        from core.literary_memory import retrieve_evidence,default_path,_connection
        from core.literary_memory_rag import search_memory_semantic
        from core.literary_identity import same_author_name,normalize_identity
        from core.ai_character_answers import _facts,_profile_facts
        from core.literary_ai import canonical_sources
        from core.literary_enrichment import narrative_coverage
        result={'read_only':True,'mysql':{},'cases':[],
                'sql_character_records':KBRecord.objects.filter(kind='character').count()}
        if args.catalogue_inventory:
            import shutil
            totals = {'records': 0, 'without_author_label': 0, 'without_author_reference': 0,
                      'without_description': 0, 'without_external_id': 0, 'openlibrary_works': 0}
            for row in KBRecord.objects.filter(kind__in=['work','edition']).values(
                    'provider','external_id','kind','payload').iterator(chunk_size=200):
                data=row['payload']
                totals['records'] += 1
                totals['without_author_label'] += not bool(data.get('author'))
                totals['without_author_reference'] += not bool(data.get('author') or data.get('author_keys'))
                totals['without_description'] += not bool(data.get('description') or data.get('synopsis'))
                totals['without_external_id'] += not bool(row['external_id'])
                totals['openlibrary_works'] += row['provider']=='openlibrary' and row['kind']=='work'
            result['catalogue_inventory']=totals
            result['free_disk_bytes']=shutil.disk_usage(Path.cwd()).free
        with connection.cursor() as cursor:
            for table in connection.introspection.table_names(cursor):
                cursor.execute('SELECT COUNT(*) FROM '+connection.ops.quote_name(table))
                result['mysql'][table]=cursor.fetchone()[0]
        database=default_path()
        with _connection(database) as db:
            result['memory_work_count']=db.execute('SELECT COUNT(*) FROM memory_works').fetchone()[0]
            result['sqlite_integrity']=db.execute('PRAGMA integrity_check').fetchone()[0]
            result['sqlite_fk_errors']=len(db.execute('PRAGMA foreign_key_check').fetchall())
        bare=lambda text:normalize_identity(text).removeprefix('la ').removeprefix('el ')
        ids=[]
        for title,author in CASES:
            books,sources=retrieve_evidence(title,limit=20)
            matches=[book for book in books if bare(book['title'])==bare(title) and same_author_name(book['author'],author)]
            sources=[s for s in sources if any(s.get('work_id')==book['work_id'] for book in matches)]
            ids.extend(book['work_id'] for book in matches)
            request={'title':title,'targets':matches,'names':[],'task':'characters','focus':'all','ambiguous':False}
            bound=canonical_sources(sources,20)
            facts=_facts(request,[_profile_facts(s,request) for s in bound])
            unused,indexed=(search_memory_semantic(title,books=matches,database=database,
                index=database.with_name(database.stem+'_rag.sqlite3')) if matches else ([],[]))
            sql=list(KBRecord.objects.filter(label__iexact=title).values('id','kind','provider','status'))[:20]
            result['cases'].append({'title':title,'author':author,'work_ids':[b['work_id'] for b in matches],
                'sql_records':sql,'sql_character_records':KBRecord.objects.filter(kind='character',label__iexact=title).count(),
                'sources':len(sources),'roles':[{'name':f['name'],'role':f['role'],'classification':f['classification'],
                    'main_character':f.get('main_character',False),'source_url':f['source']['url']} for f in facts],
                'rag_sources':len(indexed)})
        result['coverage']=narrative_coverage(database,ids)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=True,indent=2),encoding='utf8')
        print(json.dumps({'mysql_tables':len(result['mysql']),'mysql_rows':sum(result['mysql'].values()),
            'memory_works':result['memory_work_count'],'sqlite_integrity':result['sqlite_integrity'],
            'cases':[{'title':c['title'],'roles':len(c['roles']),'rag_sources':c['rag_sources']} for c in result['cases']]},ensure_ascii=True))


if __name__=='__main__':
    main()
