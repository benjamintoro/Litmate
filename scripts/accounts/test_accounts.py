"""Aceptación reproducible: sólo SQLite dentro de una carpeta de ensayo nueva."""
import argparse
import json
import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Usa un informe nuevo.')
    root = Path.cwd()
    (root / '.testtmp').mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='reader-acceptance-', dir=root / '.testtmp') as temp:
        path = Path(temp)
        os.environ.update(DB_ENGINE='sqlite', DB_SQLITE_PATH=str(path / 'bibliography.sqlite3'),
            DJANGO_SETTINGS_MODULE='litmate_project.reader_settings', LITMATE_DEMO_MODE='local',
            LITMATE_DEMO_WORKSPACE=str(path), LITMATE_ACCOUNTS_DB=str(path / 'accounts.sqlite3'),
            SECRET_KEY=secrets.token_urlsafe(64))
        import django
        django.setup()
        from django.conf import settings
        settings.DATABASES['accounts']['TEST']['NAME'] = str(path / 'test-accounts.sqlite3')
        settings.LITMATE_AI_RUNTIME_DB = path / 'runtime.sqlite3'
        from django.test.runner import DiscoverRunner
        class Runner(DiscoverRunner):
            def run_suite(self, suite, **kwargs):
                self.result = super().run_suite(suite, **kwargs)
                return self.result
        started = time.monotonic()
        runner = Runner(verbosity=1, interactive=False)
        failures = runner.run_tests(['reader_accounts.tests'])
        result = runner.result
        report = {'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
                  'seconds': time.monotonic()-started, 'real_databases_used': False,
                  'failed_tests': [{'test': str(test), 'error': error} for test, error in [*result.failures, *result.errors]]}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
        print(json.dumps({k:v for k,v in report.items() if k != 'failed_tests'}))
        return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
