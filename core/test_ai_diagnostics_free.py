import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings


class FreeDiagnosticTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.config = override_settings(LITMATE_RAG_DB=root / 'novels.sqlite3',
            LITMATE_KNOWLEDGE_DB=root / 'facts.sqlite3',
            LITMATE_KNOWLEDGE_RAG_DB=root / 'semantic.sqlite3',
            LITMATE_AI_USE_SEARXNG=True, LITMATE_SEARXNG_ENGINES=('wikipedia', 'openlibrary', 'mwmbl'),
            LITMATE_USE_GOOGLE_BOOKS_API=False)
        self.config.enable()

    def tearDown(self):
        self.config.disable()
        self.tmp.cleanup()

    def test_default_diagnostic_counts_local_files_without_network_or_creating_indexes(self):
        out = io.StringIO()
        with patch('core.books_google.read_json_url') as books, \
                patch('core.local_llm.read_json_url') as model, \
                patch('core.literary_search.search_searx') as searx:
            call_command('diagnosticar_ia', stdout=out)
        for function in (books, model, searx):
            function.assert_not_called()
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
        self.assertIn('sin sustitución de pago', out.getvalue())
        self.assertIn('wikipedia, openlibrary, mwmbl', out.getvalue())

    def test_live_without_sources_never_calls_books_or_searx_and_disables_retrieval(self):
        result = SimpleNamespace(status='answered', text='Hola, ¿cómo va tu lectura?', diagnostics={})
        assistant = SimpleNamespace(answer_model='modelo-local', guard_model='modelo-local',
            quality_checks=True, fast_recommendations=True, reply=Mock(return_value=result))
        client = SimpleNamespace(context=16384, base_url='http://127.0.0.1:11434',
            inspect_model=Mock(), usage={}, calls=0)
        with patch('core.management.commands.diagnosticar_ia.build_assistant', return_value=(assistant, client)) as build, \
                patch('core.management.commands.diagnosticar_ia.search_volumes') as books, \
                patch('core.literary_search.search_searx') as searx:
            call_command('diagnosticar_ia', live=True, sin_fuentes=True, stdout=io.StringIO())
        books.assert_not_called()
        searx.assert_not_called()
        self.assertEqual(build.call_args.kwargs['search']('consulta'), [])
        self.assertEqual(build.call_args.kwargs['web_search']('consulta'), [])

    def test_books_live_cannot_override_no_external_sources(self):
        with patch('core.management.commands.diagnosticar_ia.search_volumes') as books:
            with self.assertRaisesMessage(CommandError, 'no puede combinarse'):
                call_command('diagnosticar_ia', books_live=True, sin_fuentes=True, stdout=io.StringIO())
        books.assert_not_called()
