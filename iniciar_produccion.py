"""LitMate 1.0: arranque validado, sin dependencia del lanzador de demostración."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT=Path(__file__).resolve().parent


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin',required=True,help='Origen HTTPS público exacto; no activa DNS ni túneles.')
    parser.add_argument('--proxy',required=True,choices=['loopback-tls'])
    parser.add_argument('--port',type=int,default=8010)
    parser.add_argument('--accounts-db',type=Path,required=True)
    parser.add_argument('--runtime',type=Path,default=ROOT/'data/production/runtime')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--basic',action='store_true',help='Protección transitoria opcional; contraseña sólo en prompt oculto.')
    parser.add_argument('--isolated',action='store_true',help='Exige todas las rutas privadas bajo .testtmp.')
    parser.add_argument('--sqlite-catalog',type=Path,help='Sólo para --isolated; nunca para producción real.')
    parser.add_argument('--mysql-secret-file',type=Path,help='Credencial DPAPI preparada expresamente por el operador.')
    parser.add_argument('--google-books-sin-facturacion',action='store_true',help='Confirmación ya verificada por el propietario; no habilita facturación.')
    args=parser.parse_args(argv)
    if args.sqlite_catalog and not args.isolated:parser.error('SQLite sólo se admite en el ensayo aislado.')
    os.environ.update(DEBUG='False',LITMATE_PUBLIC_ORIGIN=args.origin,LITMATE_PROXY_MODE=args.proxy,
        LITMATE_PRODUCTION_PORT=str(args.port),LITMATE_ACCOUNTS_DB=str(args.accounts_db.resolve()),
        LITMATE_PRODUCTION_RUNTIME=str(args.runtime.resolve()),LITMATE_PRODUCTION_TESTING='1' if args.isolated else '0',
        LITMATE_ACCESS_GATE='basic' if args.basic else 'open',LITMATE_READER_EMAIL_ENABLED='0')
    from litmate_project.production_config import ProductionConfig
    from reader_accounts.production_runtime import ensure_port_free,prepare_runtime,FileLease
    config=ProductionConfig.from_environment(ROOT)
    ensure_port_free(config.port)
    prepare_runtime(config)
    if (config.runtime/'stop.request').exists():raise ValueError('Existe una solicitud de parada; retírala expresamente para reanudar.')
    from reader_accounts.signing_key import load_key
    if not config.accounts.is_file():raise ValueError('Prepara y verifica el almacén antes de arrancar; no se migra automáticamente.')
    os.environ.update(SECRET_KEY=load_key(config.accounts),DJANGO_SETTINGS_MODULE='litmate_project.production_settings')
    from contextlib import nullcontext
    if args.isolated:
        if not args.sqlite_catalog or not args.sqlite_catalog.resolve().is_relative_to(ROOT/'.testtmp'):
            raise ValueError('Falta un catálogo SQLite propio del ensayo.')
        os.environ.update(PYTHON_DOTENV_DISABLED='1',DB_ENGINE='sqlite',DB_SQLITE_PATH=str(args.sqlite_catalog.resolve()))
        for name in ('KNOWLEDGE_DB','KNOWLEDGE_RAG_DB','LITERARY_MEMORY_DB','LIBRARY_DB','LIBRARY_RAG_DB','RAG_DB'):
            os.environ['LITMATE_'+name]=str(config.runtime/(name.lower()+'.sqlite3'))
        os.environ.update(LITMATE_AUTO_ENRICHMENT='0',LITMATE_TRACE_MEMORY_ENABLED='0')
        database_environment=nullcontext()
    else:
        from iniciar_mysql_local import local_database_environment
        if args.mysql_secret_file:
            from reader_accounts.signing_key import _dpapi
            credential=args.mysql_secret_file.resolve()
            if not credential.is_relative_to(ROOT/'data/production') or credential.is_symlink():
                raise ValueError('La credencial protegida debe estar en data/production.')
            password=_dpapi(credential.read_bytes(),decrypt=True).decode('utf8')
        else:password=getpass.getpass('Contraseña MySQL local (oculta): ')
        database_environment=local_database_environment(password,google_books_no_billing=args.google_books_sin_facturacion)
        password=None
    with FileLease(config.runtime/'server.lock'),database_environment:
        import django
        django.setup()
        from django.core.management import call_command
        from reader_accounts.production_runtime import preflight
        report=preflight(config)
        call_command('check',deploy=True,databases=['default','accounts'],verbosity=0)
        print(json.dumps(report),flush=True)
        (config.runtime/'startup.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        if not report['ready']:return 1
        if args.check:return 0
        # No copia el archivo SQLite activo: usa backup API y restaura una copia
        # antes de abrir el listener. No reemplaza respaldos ni elimina versiones.
        if not config.testing:
            from scripts.accounts.backup_job import run_backup
            backup=run_backup(config.accounts,ROOT/'backups/automatic')
            if backup['status'] not in ('verified','recent_backup_valid'):
                raise ValueError('El respaldo automático está pausado o no está verificado.')
        password=getpass.getpass('Contraseña Basic transitoria (oculta, mínimo16): ') if args.basic else None
        from core.production_gateway import build_production_application
        application=build_production_application(config,password=password);password=None
        from waitress import create_server
        server=create_server(application,host='127.0.0.1',port=config.port,threads=8,url_scheme='https',
            clear_untrusted_proxy_headers=True,channel_timeout=90,max_request_body_size=2*1024*1024+65536,ident='LitMate')
        address,port=server.socket.getsockname()[:2]
        if address!='127.0.0.1' or port!=config.port:
            server.close();raise ValueError('El socket no coincide con el listener privado autorizado.')
        print(json.dumps({'actual_listener':address+':'+str(port),'access_gate':config.gate,'origin':config.origin,'pid':os.getpid()}),flush=True)
        finished=threading.Event()
        def control():
            while not finished.wait(.5):
                if (config.runtime/'stop.request').exists():
                    server.close()
                    return
        controller=threading.Thread(target=control,daemon=True);controller.start()
        try:server.run()
        except KeyboardInterrupt:pass
        finally:
            finished.set()
            server.close()
            server.task_dispatcher.shutdown(cancel_pending=True,timeout=5)
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:raise SystemExit(0)
    except Exception as error:
        print(json.dumps({'startup_failed':True,'error_class':type(error).__name__,'credentials_logged':False,
            'hint':'Revisa origen, proxy, almacenamiento, puerto y dependencias; no se migraron datos.'}),file=sys.stderr)
        raise SystemExit(1)
