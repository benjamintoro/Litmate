"""Aceptación real HTTPS/Waitress en loopback con catálogo, cuentas y proveedores ficticios."""
import argparse
from contextlib import closing
import http.client
import http.cookiejar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import secrets
import signal
import socket
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
MODEL='qwen3.5:9b-q4_K_M'
PASSWORD='Synthetic-Reader-64-Only!'


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));value=sock.getsockname()[1]
    if value==8003:raise ValueError('Puerto reservado al servidor público.')
    return value


def environment(folder,origin,backend,dependency):
    env={**os.environ, 'PYTHON_DOTENV_DISABLED':'1','DEBUG':'False',
        'DJANGO_SETTINGS_MODULE':'litmate_project.production_settings','SECRET_KEY':secrets.token_urlsafe(64),
        'DB_ENGINE':'sqlite','DB_SQLITE_PATH':str(folder/'catalog.sqlite3'),
        'LITMATE_ACCOUNTS_DB':str(folder/'accounts/users.sqlite3'),
        'LITMATE_PRODUCTION_RUNTIME':str(folder/'runtime'),'LITMATE_PUBLIC_ORIGIN':origin,
        'LITMATE_PROXY_MODE':'loopback-tls','LITMATE_PRODUCTION_TESTING':'1','LITMATE_ACCESS_GATE':'open',
        'LITMATE_PRODUCTION_PORT':str(backend), 'LITMATE_READER_EMAIL_ENABLED':'0',
        'LITMATE_OLLAMA_URL':'http://127.0.0.1:'+str(dependency),
        'LITMATE_SEARXNG_URL':'http://127.0.0.1:'+str(dependency),
        'LITMATE_AUTO_ENRICHMENT':'0','LITMATE_TRACE_MEMORY_ENABLED':'0',
        'LITMATE_LOCAL_MODEL':MODEL}
    for name in ('KNOWLEDGE_DB','KNOWLEDGE_RAG_DB','LITERARY_MEMORY_DB','LIBRARY_DB','LIBRARY_RAG_DB','RAG_DB'):
        env['LITMATE_'+name]=str(folder/'runtime'/(name.lower()+'.sqlite3'))
    return env


def seed(folder):
    from litmate_project.production_config import ProductionConfig
    from reader_accounts.production_runtime import prepare_runtime
    prepare_runtime(ProductionConfig.from_environment(ROOT))
    import django
    django.setup()
    from django.conf import settings
    from django.db import router
    from django.core.management import call_command
    call_command('migrate',database='accounts',interactive=False,verbosity=0)
    # Sólo el catálogo vacío bajo .testtmp, nunca se usa el router real para migrarlo.
    settings.DATABASE_ROUTERS=[]
    original_routers=router.routers
    router.routers=[]
    call_command('migrate',database='default',interactive=False,verbosity=0)
    settings.DATABASE_ROUTERS=['reader_accounts.router.AccountsRouter']
    router.routers=original_routers
    from django.contrib.auth.models import User
    from core.models import Autor,Libro,ConversacionIA
    from suscripciones.models import PlanSuscripcion
    for name,slug,price,limit in [('Gratuito','gratis',0,15),('Lector Pro','pro',4990,100),('Lector VIP','vip',9990,0)]:
        PlanSuscripcion.objects.create(nombre=name,slug=slug,precio=price,moneda='CLP',limite_consultas_ia_diarias=limit)
    author=Autor.objects.create(nombre='Autora sintética')
    Libro.objects.create(autor=author,titulo='La isla de prueba',google_book_id='synthetic-island',sinopsis='Una exploración ficticia.')
    other=User.objects.create_user('other-private',password=PASSWORD)
    ConversacionIA.objects.create(usuario=other,titulo='PRIVATE OTHER USER')
    User.objects.create_superuser('synthetic-operator','operator@example.invalid',PASSWORD)
    from reader_accounts.signing_key import load_key
    load_key(folder/'accounts/users.sqlite3')


class Dependencies(BaseHTTPRequestHandler):
    llm_calls=0
    ollama_down=False
    search_down=False
    def log_message(self,*args):pass
    def do_GET(self):
        body={'models':[{'name':MODEL}]};status=200
        if (self.path=='/api/tags' and type(self).ollama_down) or (self.path=='/healthz' and type(self).search_down):
            status=503;body={'status':'offline'}
        raw=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_POST(self):
        type(self).llm_calls+=1
        self.send_error(503)


class Proxy(BaseHTTPRequestHandler):
    backend=None
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass
    def do_GET(self):self.forward()
    def do_POST(self):self.forward()
    def forward(self):
        connection=http.client.HTTPConnection('127.0.0.1',type(self).backend,timeout=15)
        try:
            length=int(self.headers.get('Content-Length',0))
            headers={k:v for k,v in self.headers.items() if k.lower() not in ('connection','transfer-encoding')}
            connection.request(self.command,self.path,self.rfile.read(length) if length else None,headers)
            response=connection.getresponse();self.send_response(response.status)
            for key,value in response.getheaders():
                if key.lower() not in ('connection','transfer-encoding','server','date'):self.send_header(key,value)
            self.send_header('Connection','close');self.end_headers()
            while True:
                chunk=response.read1(8192)
                if not chunk:break
                self.wfile.write(chunk);self.wfile.flush()
        except (OSError,ValueError):
            self.close_connection=True
        finally:connection.close();self.close_connection=True


class Client:
    def __init__(self,port,cert,origin):
        self.jar=http.cookiejar.CookieJar();self.origin=origin;self.port=port
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.jar),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(cert))))
    def request(self,path,data=None,*,json_body=False,csrf=True):
        headers={'Host':urllib.parse.urlsplit(self.origin).netloc}
        if data is not None:
            headers['Origin']=self.origin
            if csrf:headers['X-CSRFToken']=next((cookie.value for cookie in self.jar if cookie.name=='csrftoken'),'')
            headers['Content-Type']='application/json' if json_body else 'application/x-www-form-urlencoded'
            data=json.dumps(data).encode() if json_body else urllib.parse.urlencode(data).encode()
        request=urllib.request.Request(f'https://127.0.0.1:{self.port}'+path,data=data,headers=headers)
        started=time.monotonic()
        try:response=self.opener.open(request,timeout=15)
        except urllib.error.HTTPError as error:response=error
        with response:
            # SSE read by line: measure first useful event separately from the full response.
            if response.headers.get_content_type()=='text/event-stream':
                first=None;chunks=[]
                for line in response:
                    chunks.append(line)
                    if first is None and line.startswith(b'data:'):first=time.monotonic()-started
                raw=b''.join(chunks)
            else:raw=response.read();first=None
            return response.status,response.headers,raw,round(time.monotonic()-started,4),first


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',type=Path,required=True);parser.add_argument('--report',type=Path)
    parser.add_argument('--seed',action='store_true');parser.add_argument('--browser',action='store_true')
    args=parser.parse_args();folder=args.folder.resolve()
    if not folder.is_relative_to(ROOT/'.testtmp'):parser.error('Sólo se admiten carpetas nuevas de ensayo.')
    if args.seed:seed(folder);return 0
    if folder.exists() or not args.report or args.report.exists():parser.error('Usa carpeta e informe nuevos.')
    folder.mkdir(parents=True);(folder/'accounts').mkdir()
    cert=folder/'tls.pem';key=folder/'tls.key'
    subprocess.run([r'C:\Program Files\Git\usr\bin\openssl.exe','req','-x509','-newkey','rsa:2048','-nodes',
        '-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=litmate.example.test',
        '-addext','subjectAltName=DNS:litmate.example.test,IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    dependency=ThreadingHTTPServer(('127.0.0.1',0),Dependencies)
    threading.Thread(target=dependency.serve_forever,daemon=True).start()
    backend=port();Proxy.backend=backend
    proxy=ThreadingHTTPServer(('127.0.0.1',0),Proxy)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert,key)
    proxy.socket=tls.wrap_socket(proxy.socket,server_side=True)
    proxy_port=proxy.server_address[1];origin=f'https://litmate.example.test:{proxy_port}'
    threading.Thread(target=proxy.serve_forever,daemon=True).start()
    env=environment(folder,origin,backend,dependency.server_address[1]);checks=[];measurements=[];process=None
    report={'real_production_access':False,'catalogue':'synthetic SQLite','model_inference':'not used; dependency fixture',
        'tls':'Python validates synthetic certificate; Edge only ignores certificate errors in its isolated profile',
        'checks':checks,'measurements':measurements}
    def check(name,condition):
        checks.append({'case':name,'passed':bool(condition)})
        if not condition:raise AssertionError(name)
    command=[sys.executable,'-B',str(ROOT/'iniciar_produccion.py'),'--origin',origin,'--proxy','loopback-tls',
        '--port',str(backend),'--accounts-db',str(folder/'accounts/users.sqlite3'),'--runtime',str(folder/'runtime'),
        '--isolated','--sqlite-catalog',str(folder/'catalog.sqlite3')]
    def start():
        child=subprocess.Popen(command,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8',errors='replace')
        lines=queue.Queue()
        def read():
            for line in child.stdout:lines.put(line)
        threading.Thread(target=read,daemon=True).start()
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            try:
                line=lines.get(timeout=.2)
                if 'actual_listener' in line:
                    info=json.loads(line);report['listener']=info['actual_listener'];report['test_pid']=info['pid'];return child
            except queue.Empty:pass
            if child.poll() is not None:
                raise ValueError('Arranque aislado falló: '+child.stderr.read()[:1800])
        child.terminate();raise TimeoutError('No apareció el listener aislado.')
    def stop(child):
        (folder/'runtime/stop.request').touch()
        child.wait(timeout=12)
    try:
        subprocess.run([sys.executable,'-B','-m','scripts.accounts.production_smoke','--seed','--folder',str(folder)],
            cwd=ROOT,env=env,check=True,stdout=subprocess.DEVNULL)
        process=start();client=Client(proxy_port,cert,origin)
        # Una muestra del proceso de ENSAYO, no del servidor público.
        sample=subprocess.run(['powershell','-NoProfile','-Command',
            'Get-Process -Id '+str(report['test_pid'])+' | Select-Object Id,CPU,WorkingSet64,PeakWorkingSet64,Threads | ConvertTo-Json -Compress'],
            capture_output=True,text=True,timeout=5)
        if sample.returncode==0:
            raw=json.loads(sample.stdout)
            report['resources_sample']={k:raw[k] for k in ('Id','CPU','WorkingSet64','PeakWorkingSet64')}
        for path in ['/','/libros/','/chat/','/registro/','/login/','/static/js/reader-library.js','/static/admin/css/base.css']:
            status,headers,body,elapsed,_=client.request(path)
            check('public_without_basic_'+path,status==200 and not headers.get('WWW-Authenticate'))
            measurements.append({'path':path,'seconds':elapsed})
        for path in ['/.env','/data/accounts/users.sqlite3','/backups/','/admin/','/auth/social/google/']:
            check('private_route_'+path,client.request(path)[0]==404)
        check('csrf_without_token',client.request('/registro/',{'username':'bad'},csrf=False)[0]==403)
        status,_,body,elapsed,first=client.request('/chatbot_query/',{'message':'Hola','request_id':'synthetic-guest-hello-0001'},json_body=True)
        check('guest_sse',status==200 and b'data: [DONE]' in body)
        measurements.append({'case':'guest_sse','seconds':elapsed,'first_event':first})
        check('guest_quota',client.request('/chatbot_query/',{'message':'Otra consulta','request_id':'synthetic-guest-hello-0002'},json_body=True)[0]==429)
        client.request('/registro/')
        status,_,body,_,_=client.request('/registro/',{'username':'https-reader','email':'https-reader@example.invalid',
            'password':PASSWORD,'password_confirm':PASSWORD})
        check('registration_persistent_open',status==200 and 'Gratuito'.encode() in body)
        check('free_plan',client.request('/cuenta/activar-gratis/',{'plan':'gratis'})[0]==200)
        book={'google_id':'https-fixture-a','titulo':'La isla de prueba','autores':'Autora sintética','imagen_url':''}
        favorite=json.loads(client.request('/favoritos/agregar/',book,json_body=True)[2]);check('favorite_created',favorite['status']=='ok')
        reading=json.loads(client.request('/api/listas/crear/',{'nombre':'HTTPS lecturas'},json_body=True)[2])
        check('list_created',reading['status']=='ok')
        check('list_book',client.request('/api/listas/agregar-libro/',{**book,'lista_id':reading['id']},json_body=True)[0]==200)
        status,_,body,elapsed,first=client.request('/chatbot_query/',{'message':'Muéstrame mis favoritos','request_id':'synthetic-private-library-0001'},json_body=True)
        check('private_library_sse',status==200 and b'La isla de prueba' in body and b'data: [DONE]' in body)
        measurements.append({'case':'private_library_sse','seconds':elapsed,'first_event':first})
        check('idempotent_quota_replay',client.request('/chatbot_query/',{'message':'Muéstrame mis favoritos','request_id':'synthetic-private-library-0001'},json_body=True)[1].get('X-LitMate-Idempotent-Replay')=='1')
        check('other_history_denied',client.request('/cuenta/conversaciones/1/')[0]==404)
        check('secure_session_cookie',any(cookie.name=='litmate_reader_sessionid' and cookie.secure for cookie in client.jar))
        check('recovery_honest_unavailable','aún no está habilitado'.encode() in client.request('/password-reset/')[2])
        check('payments_not_enabled',client.request('/suscripciones/iniciar-pago/',{'plan':'pro'})[0] in (403,404,503))
        check('admin_requires_staff','login' in client.request('/operacion/')[2].decode().lower())
        before=client.request('/api/cuota-ia/')[2]
        from scripts.accounts.backup_job import run_backup
        backup=run_backup(folder/'accounts/users.sqlite3',folder/'backups',interval_hours=0)
        check('active_backup_restored',backup['restore_verified'])
        if args.browser:
            browser_folder=ROOT/'reports/produccion_1_0_20261108'/('browser-'+folder.name)
            config={'folder':str(browser_folder),'port':proxy_port,'origin':origin,'productionOpen':True,
                    'platform':True,'platformUser':'browser-reader','platformPassword':PASSWORD,'password':'NOT-USED'}
            result=subprocess.run(['node','scripts/demo/capturar_demo.mjs'],input=json.dumps(config),cwd=ROOT,
                text=True,capture_output=True,timeout=100)
            report['browser_stdout']=result.stdout[-5000:];report['browser_stderr']=result.stderr[-2000:]
            capture=json.loads((browser_folder/'captura.json').read_text(encoding='utf8'))
            report['browser_checks']=capture['mobileChecks']
            check('edge_acceptance',result.returncode==0 and bool(capture['mobileChecks'])
                  and all(item['passed'] for item in capture['mobileChecks']) and not capture['errors'])
        stop(process);process=None
        check('controlled_stop',True)
        (folder/'runtime/stop.request').unlink()  # Únicamente el control creado por este ensayo.
        Dependencies.search_down=True
        process=start()
        check('session_survives_restart',client.request('/api/cuota-ia/')[2]==before)
        check('library_survives_restart',b'La isla de prueba' in client.request('/cuenta/biblioteca/')[2])
        startup=json.loads((folder/'runtime/startup.json').read_text(encoding='utf8'))
        check('searxng_optional',startup['ready'] and startup['services']['searxng']=='unavailable')
        # Simula un fallo sólo del PID que ESTE ensayo acaba de lanzar.
        # El bloqueo del SO debe liberarse aunque no se ejecute finally.
        test_pid=report['test_pid']
        if test_pid==os.getpid() or test_pid<=0:raise ValueError('PID aislado inválido.')
        os.kill(test_pid,signal.SIGTERM);process.wait(timeout=10);process=None
        process=start()
        check('recover_after_test_process_crash',client.request('/api/cuota-ia/')[2]==before)
        stop(process);process=None;(folder/'runtime/stop.request').unlink()
        Dependencies.ollama_down=True
        failed=subprocess.run(command+['--check'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=25)
        check('ollama_missing_fails_before_listener',failed.returncode==1 and 'actual_listener' not in failed.stdout)
        check('no_llm_calls',Dependencies.llm_calls==0)
    except Exception as error:
        report['error']=type(error).__name__+': '+str(error)
    finally:
        if process and process.poll() is None:
            try:stop(process)
            except (OSError,subprocess.TimeoutExpired):process.terminate()
        proxy.shutdown();proxy.server_close();dependency.shutdown();dependency.server_close()
        report['llm_calls']=Dependencies.llm_calls
        report['passed']=bool(checks) and all(item['passed'] for item in checks) and 'error' not in report
        args.report.parent.mkdir(parents=True,exist_ok=True)
        with args.report.open('x',encoding='utf8') as stream:json.dump(report,stream,indent=2)
        print(json.dumps({'passed':report['passed'],'checks':len(checks),'error':report.get('error'),'llm_calls':report['llm_calls']}))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
