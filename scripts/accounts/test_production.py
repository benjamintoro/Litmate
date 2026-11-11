"""Regresión de producción abierta, exclusivamente con almacenamiento sintético."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sqlite3
from tempfile import TemporaryDirectory
import time
from contextlib import closing


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('Utiliza un informe nuevo.')
    root=Path.cwd();(root/'.testtmp').mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='production-tests-',dir=root/'.testtmp') as temporary:
        folder=Path(temporary);(folder/'accounts').mkdir()
        catalog=folder/'catalog.sqlite3'
        with closing(sqlite3.connect(catalog)) as db,db:
            db.execute('CREATE TABLE core_libro(id INTEGER PRIMARY KEY)')
        os.environ.update(PYTHON_DOTENV_DISABLED='1',DEBUG='False',SECRET_KEY=secrets.token_urlsafe(64),
            DB_ENGINE='sqlite',DB_SQLITE_PATH=str(catalog),DJANGO_SETTINGS_MODULE='litmate_project.production_settings',
            LITMATE_PUBLIC_ORIGIN='https://litmate.example.test',LITMATE_PROXY_MODE='loopback-tls',
            LITMATE_ACCOUNTS_DB=str(folder/'accounts/users.sqlite3'),LITMATE_PRODUCTION_RUNTIME=str(folder/'runtime'),
            LITMATE_PRODUCTION_TESTING='1',LITMATE_ACCESS_GATE='open',LITMATE_READER_EMAIL_ENABLED='0')
        from litmate_project.production_config import ProductionConfig
        from reader_accounts.production_runtime import prepare_runtime
        prepare_runtime(ProductionConfig.from_environment(root))
        import django
        django.setup()
        from django.conf import settings
        from django.test.runner import DiscoverRunner
        settings.DATABASES['accounts']['TEST']['NAME']=str(folder/'accounts/test-users.sqlite3')
        class Runner(DiscoverRunner):
            def run_suite(self,suite,**kwargs):
                self.result=super().run_suite(suite,**kwargs);return self.result
        started=time.monotonic();runner=Runner(interactive=False,verbosity=1)
        failures=runner.run_tests(['reader_accounts.test_production'])
        report={'tests_run':runner.result.testsRun,'failures':len(runner.result.failures),'errors':len(runner.result.errors),
            'seconds':round(time.monotonic()-started,4),'production_databases_used':False,
            'failed_tests':[{'test':str(test),'error':error} for test,error in [*runner.result.failures,*runner.result.errors]]}
        import logging
        logging.shutdown()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf8') as stream:json.dump(report,stream,indent=2)
    print(json.dumps({k:v for k,v in report.items() if k!='failed_tests'}))
    return bool(failures)


if __name__=='__main__':raise SystemExit(main())
