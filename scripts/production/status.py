"""Estado local de sólo lectura: sin claves, usuarios ni contenido de mensajes."""
import argparse
import datetime
import json
from pathlib import Path
import shutil
import urllib.error
import urllib.parse
import urllib.request
from reader_accounts.operations import account_health

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin',required=True)
    parser.add_argument('--port',type=int,default=8010)
    parser.add_argument('--accounts-db',type=Path,required=True)
    parser.add_argument('--runtime',type=Path,required=True)
    args=parser.parse_args();runtime=args.runtime.resolve();accounts=args.accounts_db.resolve()
    if not runtime.is_relative_to(ROOT/'data/production') and not runtime.is_relative_to(ROOT/'.testtmp'):
        parser.error('Runtime fuera del proyecto.')
    if not accounts.is_relative_to(ROOT/'data/accounts') and not accounts.is_relative_to(ROOT/'.testtmp'):
        parser.error('Cuentas fuera del proyecto.')
    authority=urllib.parse.urlsplit(args.origin).netloc
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    health={}
    for route in ('live','ready'):
        try:
            request=urllib.request.Request(f'http://127.0.0.1:{args.port}/_health/{route}/',headers={'Host':authority})
            with opener.open(request,timeout=2) as response:health[route]=response.status
        except (OSError,urllib.error.HTTPError):health[route]='unavailable'
    summary={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'health':health,
             'accounts':account_health(accounts),'stop_requested':(runtime/'stop.request').exists()}
    for name,file in [('startup',runtime/'startup.json'),('supervisor',runtime/'supervisor.json'),
                      ('backup',ROOT/'backups/automatic/latest.json')]:
        try:
            raw=json.loads(file.read_text(encoding='utf8'))
            summary[name]={k:raw[k] for k in ('version','environment','ready','errors','warnings','services',
                'access_gate','at','restore_verified','attempt','exit_code','stopped') if k in raw}
        except (OSError,ValueError):summary[name]={'status':'no_report'}
    if runtime.is_dir():summary['free_gib']=round(shutil.disk_usage(runtime).free/1024**3,2)
    print(json.dumps(summary,indent=2))
    return 0 if health=={'live':200,'ready':200} else 1


if __name__=='__main__':raise SystemExit(main())
