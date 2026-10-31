"""Pruebas públicas acotadas: motores reales y evidencia, sin escribir conocimiento."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from urllib.parse import urlencode,urlsplit


CASES=(('novela','El nombre de la rosa','Umberto Eco'),
       ('manga','Naruto','Masashi Kishimoto'),
       ('historia','Historia de la república del Perú','Jorge Basadre'),
       ('ensayo','El infinito en un junco','Irene Vallejo'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--mode',choices=('engines','fallback'),required=True)
    args=parser.parse_args()
    if args.output.exists():
        parser.error('Utiliza una salida nueva para preservar los resultados.')
    # Configuración de prueba aislada: no carga .env, tokens ni almacenes reales.
    from django.conf import settings
    if settings.configured:
        raise ValueError('Ejecuta en un proceso nuevo.')
    os.environ.pop('DJANGO_SETTINGS_MODULE',None)
    with TemporaryDirectory(prefix='litmate-searx-quality-') as temporary:
        folder=Path(temporary)
        settings.configure(SECRET_KEY='public-searx-probe',BASE_DIR=Path.cwd(),
            INSTALLED_APPS=['django.contrib.auth','django.contrib.contenttypes','core','suscripciones'],
            DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}},
            CACHES={'default':{'BACKEND':'django.core.cache.backends.locmem.LocMemCache'}},
            LITMATE_AI_LOCK_BACKEND='sqlite',LITMATE_AI_RUNTIME_DB=folder/'runtime.sqlite3',
            LITMATE_AI_USE_WEB=True,LITMATE_AI_USE_SEARXNG=True,
            LITMATE_SEARXNG_URL='http://127.0.0.1:8080',
            LITMATE_SEARXNG_ENGINES=('wikipedia','openlibrary','mwmbl'),
            LITMATE_SEARXNG_WEB_ENGINES=('mwmbl','duckduckgo'))
        import django
        django.setup()
        from core.ai_http import read_json_url
        from core.ai_budget import request_budget
        from core.ai_concurrency import pause_provider
        from core.literary_identity import normalize_identity,same_work
        from core.literary_search import (search_searx,read_public_page,read_public_web_page,
                                          trusted_url,_catalogue_api_only)
        from core.ai_narrative_answers import _task_content
        from core.literary_sources import research_scope,research_snapshot
        report={'mode':args.mode,'started_at':datetime.now(timezone.utc).isoformat(),'cases':[],
                'real_services':True,'public_queries_only':True,'knowledge_writes':False,
                'duckduckgo_pause_simulated':args.mode=='fallback',
                'note':'Contenido recuperado no equivale a corroboración factual independiente.'}
        if args.mode=='fallback':
            # Simula un CAPTCHA previo sólo en runtime temporal; las consultas
            # a SearXNG y las lecturas de las demás fuentes sí son reales.
            pause_provider('litmate_ddg_cooldown',3600)
        def save(row):
            report['cases'].append(row)
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(report,ensure_ascii=True,indent=2),encoding='utf8')
            print(json.dumps({k:v for k,v in row.items() if k not in {'results','evidence','research'}},ensure_ascii=True),flush=True)
        for category,title,author in CASES:
            if args.mode=='engines':
                for engine in ('wikipedia','openlibrary','mwmbl'):
                    tick=time.monotonic();row={'category':category,'query':title,'engine':engine}
                    try:
                        data=read_json_url('http://127.0.0.1:8080/search?'+urlencode(
                            {'q':title,'format':'json','language':'es','engines':engine,'safesearch':1}),
                            timeout=7,local=True)
                        rows=data.get('results',[])
                        row.update(result_count=len(rows),failures=data.get('unresponsive_engines',[]),
                            results=[{k:s.get(k) for k in ('title','url','content','authors','engines')} for s in rows[:8]],
                            title_matches=sum(normalize_identity(title) in normalize_identity(s.get('title','')) for s in rows),
                            descriptive_snippets=sum(len(s.get('content',''))>=60 for s in rows))
                    except Exception as error:
                        row['error_class']=type(error).__name__
                    row['seconds']=round(time.monotonic()-tick,3);save(row)
                    time.sleep(1)
                continue
            tick=time.monotonic()
            with research_scope(pages=2),request_budget(time.monotonic()+13):
                found=search_searx(title,web=True)
                row={'category':category,'query':title,'author_target':author,
                     'status':getattr(found,'status','unknown'),'failures':getattr(found,'providers',{}),
                     'result_count':len(found),'search_seconds':round(time.monotonic()-tick,3),
                     'results':list(found),'evidence':[]}
                # Sólo destinos que el adaptador ya admitió. Nunca URL privada,
                # texto del lector, extracción comercial masiva ni bypass robots.
                relevant=[s for s in found if normalize_identity(title) in normalize_identity(s.get('title',''))
                          and not _catalogue_api_only(s['url'])]
                for source in relevant[:2]:
                    url=source['url'];start=time.monotonic()
                    try:
                        query='"'+title+'" '+author+(' argumento' if category in {'novela','manga'} else ' contenido')
                        result=(read_public_page(url,query,details=True) if trusted_url(url)
                                else read_public_web_page(url,query,details=True))
                        result=result if isinstance(result,dict) else {}
                        body=result.get('description','') if result.get('status')=='ok' else ''
                        candidate={**source,**result,'description':body,'read_mode':'pasaje de página pública'}
                        bound=same_work(candidate,{'title':title,'author':author}) if body else False
                        row['evidence'].append({'url':url,'status':result.get('status','not_read'),
                            'seconds':round(time.monotonic()-start,3),'chars':len(body),'identity_bound':bound,
                            'content_candidate':bool(bound and _task_content({'task':'summary'},candidate)),
                            'description':body,'identity_text':result.get('identity_text','')})
                    except Exception as error:
                        row['evidence'].append({'url':url,'error_class':type(error).__name__})
                row['research']=research_snapshot()
            row['seconds']=round(time.monotonic()-tick,3)
            row['usable_content_sources']=sum(bool(x.get('content_candidate')) for x in row['evidence'])
            save(row)


if __name__=='__main__':
    main()
