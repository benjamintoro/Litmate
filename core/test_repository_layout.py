"""Compatibilidad del primer lote: CLI real y estructura, sin servicios externos."""
import importlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from unittest import TestCase

ROOT = Path(__file__).resolve().parent.parent


def execute(script, arguments, cwd):
    return subprocess.run([sys.executable, '-B', str(ROOT / script), *map(str, arguments)],
        cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)


class CanonicalToolTests(TestCase):
    def test_old_and_new_help_work_from_another_directory(self):
        for name in ('analizar_evaluacion_ia', 'resumir_benchmark_ia'):
            with self.subTest(tool=name), tempfile.TemporaryDirectory() as directory:
                old = execute(name + '.py', ['--help'], directory)
                new = execute('scripts/analysis/' + name + '.py', ['--help'], directory)
                self.assertEqual(old.returncode, 0, old.stderr)
                self.assertEqual(new.returncode, 0, new.stderr)
                # argparse muestra el script invocado, pero conserva los flags.
                clean = lambda value: re.sub(r'\S*' + name + r'\.py', '<tool>', value)
                self.assertEqual(clean(old.stdout), clean(new.stdout))

    def test_benchmark_summary_outputs_are_equivalent(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / 'input.json'
            source.write_text(json.dumps({'turns': [{'case': 'synthetic', 'turn': 1,
                'seconds': 2, 'status': 'answered', 'model_calls': 0}]}), encoding='utf-8')
            outputs = []
            for index, script in enumerate(('resumir_benchmark_ia.py', 'scripts/analysis/resumir_benchmark_ia.py')):
                output = base / f'summary{index}.json'
                result = execute(script, [source, '--output', output], directory)
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(output.read_text(encoding='utf-8'))
                payload.pop('generated_at_utc')
                outputs.append(payload)
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(outputs[0]['global']['answered_under_30_seconds'], 1)

    def test_evaluation_analysis_keeps_relative_paths_and_results(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'run/case').mkdir(parents=True)
            (base / 'matrix.json').write_text(json.dumps({'cases': [{'id': 'case',
                'must_include': ['faro'], 'expected_status': ['answered']}]}), encoding='utf-8')
            (base / 'run/resumen.json').write_text('{"cases": []}', encoding='utf-8')
            (base / 'run/case/conversacion.json').write_text(json.dumps([
                {'status': 'answered', 'answer': 'El faro.', 'seconds': 1}]), encoding='utf-8')
            outputs = []
            for index, script in enumerate(('analizar_evaluacion_ia.py', 'scripts/analysis/analizar_evaluacion_ia.py')):
                output = f'analysis{index}.json'
                result = execute(script, ['--matrix', 'matrix.json', '--report', 'run', '--output', output], directory)
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs.append(json.loads((base / output).read_text(encoding='utf-8')))
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(outputs[0]['overall_pass'], 1)


class LayoutCompatibilityTests(TestCase):
    def test_legacy_imports_share_one_implementation(self):
        for name in ('analizar_evaluacion_ia', 'resumir_benchmark_ia'):
            with self.subTest(tool=name):
                old = importlib.import_module(name)
                new = importlib.import_module('scripts.analysis.' + name)
                self.assertIs(old, new)

    def test_inventory_finds_relative_dynamic_and_data_dependencies(self):
        from scripts.repository.inventory import collect
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'core/data').mkdir(parents=True)
            (base / 'core/__init__.py').write_text('', encoding='utf-8')
            (base / 'core/sample.py').write_text('from . import other\nimport importlib\n'
                'importlib.import_module("core.other")\nROOT=__file__\n', encoding='utf-8')
            (base / 'core/other.py').write_text('', encoding='utf-8')
            (base / 'core/data/sample.json').write_text('{}', encoding='utf-8')
            (base / '.env').write_text('PRIVATE=must-not-be-in-inventory', encoding='utf-8')
            result = collect(base)
            self.assertFalse(result['parse_errors'])
            self.assertTrue(any(row['kind'] == 'relative' for row in result['imports']))
            self.assertEqual(result['dynamic_imports'][0]['module'], 'core.other')
            self.assertTrue(result['file_anchors'])
            self.assertIn('core/data/sample.json', [row['origin'] for row in result['files']])
            self.assertNotIn('must-not-be-in-inventory', json.dumps(result))

    def test_django_identity_urls_and_migration_labels_stay_the_same(self):
        from django.apps import apps
        from django.db.migrations.loader import MigrationLoader
        from django.urls import resolve
        from django.test import override_settings
        self.assertEqual(apps.get_app_config('core').name, 'core')
        self.assertEqual(apps.get_app_config('suscripciones').name, 'suscripciones')
        self.assertEqual(resolve('/chatbot_query/').func.__module__, 'core.literary_ai_views')
        # El ejecutor aislado desactiva migraciones para crear tablas temporales.
        # Inspeccionar su identidad en disco sin aplicar ninguna migración.
        with override_settings(MIGRATION_MODULES={}):
            self.assertIn(('core', '0001_initial'), MigrationLoader(None).disk_migrations)

    def test_document_entrypoints_and_archives_exist(self):
        from scripts.repository.inventory import MOVES
        for origin, destination in MOVES.items():
            with self.subTest(path=destination):
                self.assertTrue((ROOT / destination).is_file())
        for name in ('README.md', 'LEEME.md', 'MYSQL_LOCAL.md', 'README_ASISTENTE_IA.md',
                     'manage.py', 'iniciar_mysql_local.py', 'verificar_proyecto.py',
                     'docker-compose.ia.yml', '.env.example', 'requirements.txt'):
            self.assertTrue((ROOT / name).is_file())
