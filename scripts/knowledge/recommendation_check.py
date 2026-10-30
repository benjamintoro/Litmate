"""Conversación reproducible en MySQL local, contraseña oculta, sin importar libros."""
import argparse
import getpass
import json
import os
from pathlib import Path
from .expand_catalog import write_new

BASELINE=('Recomiéndame libros de crimen','Más libros de crimen','Otro que no sea ese','Libros de fantasía')
AFTER=(*BASELINE[:3],'Dame diferentes','Ahora de fantasía','Más libros de fantasía',
       'Ahora de romance','Que no sea de Stephen King','Ya leí ese','No me gustó ninguno')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--after',action='store_true')
    parser.add_argument('--diagnose',action='store_true')
    parser.add_argument('--sql-only',action='store_true')
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Elige otra salida.')
    from iniciar_mysql_local import local_database_environment
    password=getpass.getpass('Contraseña MySQL local (oculta): ')
    with local_database_environment(password,development_http=True):
        password=None
        os.environ.setdefault('DJANGO_SETTINGS_MODULE','litmate_project.settings')
        import django;django.setup()
        from core.bibliographic_http_probe import run_conversation
        if args.sql_only:
            import time,statistics
            from django.db import connection
            from django.test.utils import CaptureQueriesContext
            from core.bibliographic_repository import genre_sources,digest
            from core.knowledge_models import KBRelation
            report={}
            for code in ('crime','fantasy','romance','science_fiction'):
                times=[];queries=[];count=0
                for repeat in range(20):
                    start=time.monotonic()
                    with CaptureQueriesContext(connection) as captured:count=len(genre_sources([code]))
                    times.append((time.monotonic()-start)*1000);queries.append(len(captured))
                plan=KBRelation.objects.filter(target_id=digest('classification','genre',code),current=True,
                    record__status='source_metadata').select_related('record').order_by('record_id')[:480].explain(format='JSON')
                report[code]={'candidates':count,'queries_per_call':max(queries),'p50_ms':statistics.median(times),
                    'p95_ms':sorted(times)[18],'explain':json.loads(plan)}
        elif args.diagnose:
            from core.genre_recommendations import genre_answer,remember_recommendations
            from core.literary_conversation import resolve_topic_context,remember_topic
            state={};report=[]
            for message in AFTER:
                context=resolve_topic_context(message,state)
                context['recommendation_state']=state.get('recommendations',{})
                result=genre_answer(message,[],context)
                report.append({'question':message,'context':context,'answer':result.text if result else None})
                if result is None:break
                remember_recommendations(state,message,context,result);remember_topic(state,message,context)
        else:
            report=run_conversation(AFTER if args.after else BASELINE)
        write_new(args.output,report)
        summary=([{'question':row['question'],'status':row.get('status'),'books':len(row.get('books',[])),
                   'seconds':row.get('seconds')} for row in report] if isinstance(report,list) else
                 {code:{key:value for key,value in row.items() if key!='explain'} for code,row in report.items()})
        print(json.dumps(summary,ensure_ascii=True))


if __name__=='__main__':main()
