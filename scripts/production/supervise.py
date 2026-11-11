"""Supervisor de Waitress opcional: reinicios limitados, sin instalar servicios."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from reader_accounts.production_runtime import FileLease

ROOT=Path(__file__).resolve().parents[2]


def delays(restarts):
    if not 0<=restarts<=3:raise ValueError('Se permiten entre cero y tres reinicios.')
    return [0,5,15,60][:restarts+1]


def run_supervised(command,runtime,retry_delays):
    """Una instancia y como máximo cuatro intentos; estado sin stdout sensible."""
    if not 1<=len(retry_delays)<=4 or any(not 0<=n<=60 for n in retry_delays):
        raise ValueError('Política de reintentos inválida.')
    with FileLease(runtime/'supervisor.lock'):
        for attempt,wait in enumerate(retry_delays):
            for _ in range(wait):
                if (runtime/'stop.request').exists():return 0
                time.sleep(1)
            if (runtime/'stop.request').exists():return 0
            child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
            last={}
            for line in child.stdout:
                try:
                    record=json.loads(line)
                    if 'actual_listener' in record:last={'pid':record['pid'],'listener':record['actual_listener']}
                except (ValueError,TypeError,KeyError):pass
            code=child.wait()
            state={**last,'attempt':attempt+1,'exit_code':code,'at':time.time(),
                   'stopped':(runtime/'stop.request').exists()}
            (runtime/'supervisor.json').write_text(json.dumps(state,indent=2),encoding='utf8')
            if state['stopped'] or code==0:return 0
        return 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin',required=True)
    parser.add_argument('--port',type=int,default=8010)
    parser.add_argument('--accounts-db',type=Path,required=True)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--mysql-secret-file',type=Path,required=True)
    parser.add_argument('--restarts',type=int,default=3)
    parser.add_argument('--google-books-sin-facturacion',action='store_true')
    args=parser.parse_args()
    if args.port==8003:parser.error('El supervisor no administra la demo pública de 8003.')
    runtime=args.runtime.resolve()
    if not runtime.is_relative_to(ROOT/'data/production') or not (runtime/'production-owner.json').is_file():
        parser.error('Valida primero el arranque --check; no se adopta otro runtime.')
    if not args.mysql_secret_file.is_file():parser.error('Prepara antes la credencial DPAPI local.')
    command=[sys.executable,'-B',str(ROOT/'iniciar_produccion.py'),'--origin',args.origin,'--proxy','loopback-tls',
        '--port',str(args.port),'--accounts-db',str(args.accounts_db.resolve()),'--runtime',str(runtime),
        '--mysql-secret-file',str(args.mysql_secret_file.resolve())]
    if args.google_books_sin_facturacion:command.append('--google-books-sin-facturacion')
    return run_supervised(command,runtime,delays(args.restarts))


if __name__=='__main__':raise SystemExit(main())
