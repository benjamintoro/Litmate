"""Proyecta clasificaciones a relaciones ya existentes, sin cambiar las fichas."""
import argparse
import getpass
import json
import os
from pathlib import Path
import time
from .expand_catalog import write_new


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--post-backup',type=Path)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Usa una salida nueva.')
    from iniciar_mysql_local import local_database_environment
    password=getpass.getpass('Contraseña MySQL local (oculta): ')
    with local_database_environment(password):
        password=None;os.environ.setdefault('DJANGO_SETTINGS_MODULE','litmate_project.settings')
        import django;django.setup()
        from core.database_transfer import verify_backup
        from core.bibliographic_expansion import preserve_expansion_rows
        from core.bibliographic_repository import index_classifications,genre_sources
        from core.knowledge_models import KBRecord,KBRelation,KBProjection
        from core.bibliographic_repository import digest
        from core.models import Libro
        from core.literary_genres import TAXONOMY,VERSION
        from core.genre_recommendations import local_genre_sources
        from django.db.models import Count
        manifest=verify_backup(args.backup)
        preserve_expansion_rows(args.backup,manifest)
        checkpoint=args.output.with_suffix('.checkpoint.json')
        cursor='';scanned=0
        if checkpoint.exists():
            state=json.loads(checkpoint.read_text(encoding='utf-8'))
            if state['version']!=VERSION:raise ValueError('Cambió la taxonomía; usa otro checkpoint.')
            cursor=state['cursor'];scanned=state['scanned']
        started=time.monotonic()
        while True:
            batch=index_classifications(after=cursor)
            scanned+=batch['scanned'];cursor=batch['cursor']
            checkpoint.parent.mkdir(parents=True,exist_ok=True)
            temporary=checkpoint.with_suffix('.tmp')
            temporary.write_text(json.dumps({'version':VERSION,'cursor':cursor,'scanned':scanned}),encoding='utf-8')
            temporary.replace(checkpoint)
            if batch['complete']:break
            time.sleep(.05)
        KBProjection.objects.update_or_create(id=digest('classification-index',VERSION),defaults={
            'last_rowid':scanned,'counters':{'records':scanned,'classification_relations':
                KBRelation.objects.filter(predicate__in=['genre','format','audience'],current=True).count()}})
        report={'taxonomy':VERSION,'scanned':scanned,'seconds':time.monotonic()-started,
            'records_unchanged_count':KBRecord.objects.count(),'legacy_books':Libro.objects.count(),
            'classifications':list(KBRelation.objects.filter(predicate__in=['genre','format','audience'],current=True)
                .values('predicate','target_external_id').annotate(count=Count('id'))),
            'counts':{code:{'sql_sample_up_to_160':len(genre_sources([code])),
                'local_books':len(local_genre_sources([code]))} for code in TAXONOMY},
            'integrity':preserve_expansion_rows(args.backup,manifest)}
        if args.post_backup:
            from core.database_transfer import create_backup
            final=create_backup(args.post_backup);verify_backup(args.post_backup)
            report['post_backup']={'path':str(args.post_backup),'tables':len(final['database']['tables']),
                'rows':sum(table['count'] for table in final['database']['tables'].values())}
        write_new(args.output,report)
        print(json.dumps({key:value for key,value in report.items() if key!='integrity'},ensure_ascii=True))


if __name__=='__main__':main()
