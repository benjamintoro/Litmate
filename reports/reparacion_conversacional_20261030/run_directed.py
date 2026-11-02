"""Pruebas dirigidas con SQLite y almacenes auxiliares desechables."""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    with TemporaryDirectory(prefix='litmate-conversation-tests-') as temporary:
        folder = Path(temporary)
        os.environ['DB_ENGINE'] = 'sqlite'
        os.environ['DB_SQLITE_PATH'] = str(folder / 'django.sqlite3')
        os.environ['DJANGO_SETTINGS_MODULE'] = 'litmate_project.settings'
        import django
        django.setup()
        from django.test import override_settings
        from django.test.runner import DiscoverRunner
        from scripts.knowledge.knowledge_campaign import STORES
        modules = json.loads((ROOT / 'reports/calidad_literaria_20261030/tests_directed.json').read_text(
            encoding='utf-8'))['modules']
        modules += [
            'core.test_conversational_relevance', 'core.test_related_recommendation_cards',
            'core.test_recommendation_count', 'core.test_recommendation_relations',
            'core.test_recommendation_grounding', 'core.test_recommendation_cards_regression',
            'core.test_recommendation_candidates', 'core.test_topic_task_boundaries',
            'core.test_topic_return_memory', 'core.test_literary_conversation',
            'core.test_topic_intent', 'core.test_free_topic_recommendations',
            'core.test_local_audit_slots', 'core.test_local_ai.LocalProviderTests',
            'core.test_chat_deadline',
            'core.test_ai_answer_cache',
        ]
        class RecordingRunner(DiscoverRunner):
            def run_suite(self, suite, **kwargs):
                self.result = super().run_suite(suite, **kwargs)
                return self.result
        overrides = {key: folder / (key.lower() + '.sqlite3') for key in STORES}
        overrides.update(LITMATE_AI_RUNTIME_DB=folder / 'runtime.sqlite3',
            LITMATE_AI_ANSWER_CACHE_DB=folder / 'answers.sqlite3',
            LITMATE_AI_STREAM_CACHE_DB=folder / 'stream.sqlite3',
            CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                'LOCATION': 'conversation-regressions'}})
        started = time.monotonic()
        with override_settings(**overrides):
            runner = RecordingRunner(verbosity=1, interactive=False)
            failures = runner.run_tests(modules)
        result = runner.result
        report = {'modules': modules, 'tests_run': result.testsRun,
            'failures': len(result.failures), 'errors': len(result.errors),
            'skipped': len(result.skipped), 'seconds': round(time.monotonic() - started, 3),
            'production_databases_used': False,
            'failed_tests': [{'test': str(test), 'traceback': message}
                             for test, message in [*result.failures, *result.errors]]}
        output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name('tests_final.json')
        with output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=True, indent=2)
        print(json.dumps({key: report[key] for key in ('tests_run', 'failures', 'errors', 'seconds')}))
        return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
