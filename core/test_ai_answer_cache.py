"""Caché exacta aislada: validez y privacidad antes que tasa de aciertos."""
import copy
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase
from .ai_answer_cache import get_answer, put_answer, cache_key
from .ai_quick_answers import quick_answer


class AnswerCacheTests(SimpleTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'answers.sqlite3'
        self.version = patch('core.ai_answer_cache._revision', return_value=['test-v1'])
        self.version.start()
        self.addCleanup(self.version.stop)
        self.question = '¿Quién escribió El principito?'
        self.result = quick_answer(self.question)
        self.assertIsNotNone(self.result)

    def test_reuses_only_verified_result_for_same_owner(self):
        self.assertTrue(put_answer(self.question, {}, 'session:a', self.result, database=self.path))
        result = get_answer(self.question, {}, 'session:a', database=self.path)
        self.assertEqual(result.text, self.result.text)
        self.assertTrue(result.diagnostics['exact_answer_cache_hit'])
        self.assertIsNone(get_answer(self.question, {}, 'session:b', database=self.path))

    def test_explicit_authorship_can_ignore_irrelevant_previous_turns(self):
        self.assertEqual(cache_key(self.question, {'turns': []}, 'session:a'),
                         cache_key(self.question, {'turns': [{'answer': 'otra obra'}]}, 'session:a'))

    def test_deictic_and_ordinal_references_preserve_context_and_order(self):
        for question in ('¿Quién escribió ese libro?', '¿Y el segundo?', '¿Y qué pasa con Det?'):
            self.assertNotEqual(cache_key(question, {'books': ['a', 'b']}, 'session:a'),
                                cache_key(question, {'books': ['b', 'a']}, 'session:a'))

    def test_same_title_with_different_author_in_history_cannot_collide(self):
        left = {'active_work': {'title': 'El lugar', 'author': 'Autora A'}}
        right = {'active_work': {'title': 'El lugar', 'author': 'Autora B'}}
        self.assertNotEqual(cache_key('Quién escribió El lugar', left, 'session:a'),
                            cache_key('Quién escribió El lugar', right, 'session:a'))

    def test_knowledge_revision_invalidates_result(self):
        put_answer(self.question, {}, 'session:a', self.result, database=self.path)
        with patch('core.ai_answer_cache._revision', return_value=['test-v2']):
            self.assertIsNone(get_answer(self.question, {}, 'session:a', database=self.path))

    def test_expired_and_llm_generated_answers_are_not_stored(self):
        result = copy.deepcopy(self.result)
        result.sources[0]['expires_at'] = '2000-01-01T00:00:00+00:00'
        self.assertFalse(put_answer(self.question, {}, 'session:a', result, database=self.path))
        result = copy.deepcopy(self.result)
        result.diagnostics = {'model_calls': 1}
        self.assertFalse(put_answer(self.question, {}, 'session:a', result, database=self.path))

    def test_audited_web_reference_is_reused_without_turning_it_into_a_book(self):
        from .ai_quick_answers import reference_answer
        source = {'title': 'El nombre de la rosa', 'author': 'Fuente web',
                  'description': 'El nombre de la rosa es una novela de Umberto Eco. '
                                 'La historia sigue a Guillermo de Baskerville en una abadía medieval.',
                  'url': 'https://es.wikipedia.org/wiki/El_nombre_de_la_rosa',
                  'kind': 'web', 'source': 'Wikipedia',
                  'read_mode': 'pasaje de sección de artículo público'}
        question = '¿De qué trata El nombre de la rosa?'
        reference = reference_answer(question, [source])
        self.assertIsNotNone(reference)
        self.assertTrue(put_answer(question, {}, 'session:a', reference, database=self.path))
        cached = get_answer(question, {}, 'session:a', database=self.path)
        self.assertIsNotNone(cached)
        self.assertEqual(cached.text, reference.text)
        self.assertEqual(cached.books, [])
        self.assertTrue(cached.diagnostics['web_reference_quick_answer'])
        self.assertTrue(cached.diagnostics['exact_answer_cache_hit'])

    def test_a_reference_whose_text_no_longer_matches_its_audit_is_rejected(self):
        from .ai_quick_answers import reference_answer
        source = {'title': 'El nombre de la rosa', 'author': 'Fuente web',
                  'description': 'El nombre de la rosa es una novela de Umberto Eco.',
                  'url': 'https://es.wikipedia.org/wiki/El_nombre_de_la_rosa',
                  'kind': 'web', 'source': 'Wikipedia'}
        question = '¿De qué trata El nombre de la rosa?'
        reference = reference_answer(question, [source])
        self.assertIsNotNone(reference)
        reference.text = reference.text.replace('Umberto Eco', 'Un autor inventado')
        self.assertFalse(put_answer(question, {}, 'session:a', reference, database=self.path))

    def test_forged_authorship_is_rejected_and_query_not_stored(self):
        result = copy.deepcopy(self.result)
        result.text = '**El principito** es una obra de **Un autor falso**.'
        self.assertFalse(put_answer(self.question, {}, 'session:a', result, database=self.path))
        put_answer(self.question, {}, 'session:a', self.result, database=self.path)
        with closing(sqlite3.connect(self.path)) as db:
            key = db.execute('SELECT cache_key FROM answers').fetchone()[0]
            self.assertEqual(len(key), 64)
            self.assertNotIn(self.question, key)

    def test_foreign_database_is_not_modified(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE private_data(secret TEXT)')
        self.assertFalse(put_answer(self.question, {}, 'session:a', self.result, database=self.path))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),
                             [('private_data',)])
