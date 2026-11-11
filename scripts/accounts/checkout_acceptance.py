"""Aceptación conjunta de checkout y comunidad, con datos exclusivamente sintéticos."""
import argparse
import json
import os
from pathlib import Path
import queue
import ssl
import subprocess
import sys
import threading
import time

from scripts.accounts import production_smoke as smoke
from scripts.accounts.community_acceptance import rows, seed_and_upgrade

ROOT = Path(__file__).resolve().parents[2]


def seed(folder):
    migration = seed_and_upgrade(folder)
    from suscripciones.models import PlanSuscripcion
    PlanSuscripcion.objects.filter(precio=0).update(limite_favoritos=20)
    PlanSuscripcion.objects.filter(slug='pro').update(limite_favoritos=100)
    PlanSuscripcion.objects.filter(slug='vip').update(limite_favoritos=0)
    (folder/'checkout-synthetic.json').write_text(json.dumps({'synthetic_checkout': True}), encoding='utf8')
    (folder/'migration.json').write_text(json.dumps(migration), encoding='utf8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--seed', action='store_true')
    args = parser.parse_args()
    folder, output = args.folder.resolve(), args.output.resolve()
    if not folder.is_relative_to(ROOT/'.testtmp') or not output.is_relative_to(ROOT/'reports'):
        parser.error('Usa rutas aisladas de .testtmp y reports.')
    if args.seed:
        seed(folder)
        return 0
    if folder.exists() or output.exists():
        parser.error('Usa destinos nuevos.')
    folder.mkdir(parents=True)
    (folder/'accounts').mkdir()
    output.parent.mkdir(parents=True, exist_ok=True)
    pictures = output.parent/'capturas'
    pictures.mkdir(exist_ok=False)
    cert, key = folder/'tls.pem', folder/'tls.key'
    subprocess.run([r'C:\Program Files\Git\usr\bin\openssl.exe','req','-x509','-newkey','rsa:2048','-nodes',
        '-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=litmate.example.test',
        '-addext','subjectAltName=DNS:litmate.example.test,IP:127.0.0.1'],check=True,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    dependency = smoke.ThreadingHTTPServer(('127.0.0.1',0),smoke.Dependencies)
    threading.Thread(target=dependency.serve_forever,daemon=True).start()
    backend = smoke.port()
    smoke.Proxy.backend = backend
    proxy = smoke.ThreadingHTTPServer(('127.0.0.1',0),smoke.Proxy)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert,key)
    proxy.socket = tls.wrap_socket(proxy.socket,server_side=True)
    origin = f'https://litmate.example.test:{proxy.server_address[1]}'
    env = smoke.environment(folder,origin,backend,dependency.server_address[1])
    env.update(LITMATE_COMMUNITY_ENABLED='1',LITMATE_SIMULATED_CHECKOUT_ENABLED='1',
               LITMATE_CHECKOUT_TEST_SCENARIOS='1',LITMATE_COMMUNITY_TEST_IMAGES=str(folder/'uploads'))
    stop = folder/'runtime/stop.request'
    command = [sys.executable,'-B',str(ROOT/'iniciar_produccion.py'),'--origin',origin,'--proxy','loopback-tls',
        '--port',str(backend),'--accounts-db',str(folder/'accounts/users.sqlite3'),
        '--runtime',str(folder/'runtime'),'--isolated','--sqlite-catalog',str(folder/'catalog.sqlite3')]
    report = {'synthetic_only':True,'public_services_changed':False,'checks':{}}
    process = None

    def start():
        if stop.exists():
            stop.unlink()
        child = subprocess.Popen(command,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                  text=True,encoding='utf8',errors='replace')
        lines = queue.Queue()
        def reader():
            for line in child.stdout:
                lines.put(line)
        threading.Thread(target=reader,daemon=True).start()
        deadline = time.monotonic()+25
        while time.monotonic()<deadline:
            try:
                if 'actual_listener' in lines.get(timeout=.2):
                    return child
            except queue.Empty:
                pass
            if child.poll() is not None:
                raise RuntimeError(child.stderr.read()[:2000])
        child.terminate()
        raise TimeoutError('Arranque aislado incompleto.')

    def halt():
        stop.touch()
        process.wait(timeout=15)

    def browser(script, target, *extra):
        subprocess.run([str(args.node),str(ROOT/'scripts/accounts'/script),origin,str(pictures),
                        str(target),str(report['migration']['book_id']),*extra],
                       cwd=ROOT,env=env,check=True,timeout=180)
        data = json.loads(target.read_text(encoding='utf8'))
        if not data.get('passed'):
            raise AssertionError('El navegador informó una comprobación fallida.')
        return data

    threading.Thread(target=proxy.serve_forever,daemon=True).start()
    try:
        subprocess.run([sys.executable,'-B','-m','scripts.accounts.checkout_acceptance','--seed',
            '--folder',str(folder),'--output',str(output),'--node',str(args.node)],cwd=ROOT,env=env,
            check=True,stdout=subprocess.DEVNULL)
        report['migration'] = json.loads((folder/'migration.json').read_text())
        process = start()
        report['community'] = browser('community_browser.cjs',output.parent/'comunidad_browser.json')
        report['checkout'] = browser('checkout_browser.cjs',output.parent/'checkout_browser.json')
        before = rows(folder/'accounts/users.sqlite3')
        halt()
        process = start()
        report['checks']['rows_survive_restart'] = rows(folder/'accounts/users.sqlite3') == before
        report['restart'] = browser('checkout_browser.cjs',output.parent/'reinicio_browser.json','restart')
        halt()
        process = None
        # Renovación protegida con fecha derivada del período guardado por el navegador.
        state = json.loads((pictures/'checkout_state.json').read_text())
        renewal = subprocess.run([sys.executable,'-B','-m','scripts.accounts.renew_simulated',
            '--folder',str(folder),'--at',state['renewAt'],'--user','marcos-demo'],
            cwd=ROOT,env=env,text=True,capture_output=True,check=True)
        report['renewal'] = json.loads(renewal.stdout)
        report['checks']['scheduled_renewal'] = len(report['renewal']['renewals']) == 1
        duplicate = subprocess.run([sys.executable,'-B','-m','scripts.accounts.renew_simulated',
            '--folder',str(folder),'--at',state['renewAt'],'--user','marcos-demo'],
            cwd=ROOT,env=env,text=True,capture_output=True,check=True)
        report['checks']['renewal_retry_no_duplicate'] = not json.loads(duplicate.stdout)['renewals']
        for action,database in [('crear',folder/'accounts/users.sqlite3'),
                                ('restaurar-nuevo',folder/'restored/accounts/users.sqlite3')]:
            subprocess.run([sys.executable,'-B','-m','scripts.accounts.backup_store',action,
                '--database',str(database),'--folder',str(folder/'backup')],cwd=ROOT,env=env,
                check=True,stdout=subprocess.DEVNULL)
        report['checks']['backup_restored_exactly'] = rows(folder/'accounts/users.sqlite3') == rows(folder/'restored/accounts/users.sqlite3')
        report['checks']['no_llm_inference'] = smoke.Dependencies.llm_calls == 0
        report['passed'] = all(report['checks'].values())
    except Exception as error:
        report.update(passed=False,error=str(error))
    finally:
        if process is not None and process.poll() is None:
            halt()
        proxy.shutdown()
        dependency.shutdown()
        output.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
    print(json.dumps({'passed':report.get('passed'),'error':report.get('error'),'checks':report['checks']}))
    return 0 if report.get('passed') else 1


if __name__=='__main__':
    raise SystemExit(main())
