"""Regresiones de la demo con Django SQLite y auxiliares temporales, sin producción."""
import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time

MODULES = [
    'core.test_demo_gateway', 'core.test_detective_demo',
    'core.test_related_recommendation_cards', 'core.test_genre_recommendations',
    'core.test_character_alias_generalization', 'core.test_character_alias_holdout',
    'core.test_literary_cohesion', 'core.test_http_work_focus',
    'core.test_conversational_relevance', 'core.test_literary_conversation',
    'core.test_identity_recommendation_references', 'core.test_recommendation_count',
    'core.test_recommendation_cards_regression', 'core.test_ai_public_details',
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('El informe ya existe; usa otro nombre.')
    with TemporaryDirectory(prefix='litmate-demo-tests-') as temporary:
        folder = Path(temporary)
        os.environ.update(DB_ENGINE='sqlite', DB_SQLITE_PATH=str(folder / 'django.sqlite3'),
                          DJANGO_SETTINGS_MODULE='litmate_project.settings')
        import django
        django.setup()
        from django.test import override_settings
        from django.test.runner import DiscoverRunner
        from scripts.knowledge.knowledge_campaign import STORES

        class Runner(DiscoverRunner):
            def run_suite(self, suite, **kwargs):
                self.result = super().run_suite(suite, **kwargs)
                return self.result

        overrides = {key: folder / (key.lower() + '.sqlite3') for key in STORES}
        overrides.update({key: folder / (key.lower() + '.sqlite3') for key in (
            'LITMATE_AI_RUNTIME_DB', 'LITMATE_AI_ANSWER_CACHE_DB', 'LITMATE_AI_STREAM_DB')})
        started = time.monotonic()
        with override_settings(**overrides):
            runner = Runner(verbosity=1, interactive=False)
            failures = runner.run_tests(MODULES)
        result = runner.result
        report = {'modules': MODULES, 'tests_run': result.testsRun, 'failures': len(result.failures),
                  'errors': len(result.errors), 'skipped': len(result.skipped),
                  'seconds': round(time.monotonic() - started, 3), 'production_databases_used': False,
                  'failed_tests': [{'test': str(test), 'traceback': message}
                                   for test, message in [*result.failures, *result.errors]]}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=True, indent=2)
        print(json.dumps({key: report[key] for key in ('tests_run', 'failures', 'errors', 'seconds')}))
        return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
