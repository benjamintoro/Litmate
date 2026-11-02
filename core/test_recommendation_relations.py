"""Las referencias de recomendación buscan otras fichas, no repiten la base."""
from unittest.mock import Mock

from django.test import SimpleTestCase

from .literary_ai import LiteraryAssistant, canonical_sources
from .test_literary_ai import FakeLLM, ROUTE
from .test_identity_recommendation_references import DUNE, MESSIAH, PAPELUCHO
from .literary_identity import same_author_name, same_work


def accepted(*books):
    sources = canonical_sources([{**book, 'description': 'Novela de ciencia ficción.',
                                  'categories': ['Science fiction']} for book in books])
    return [{'accepted': True, 'question': 'Recomiéndame una novela',
             'answer': 'Una lectura.', 'books': list(books), 'sources': sources}]


class RecommendationRelationsIntegrationTests(SimpleTestCase):
    def test_ambiguous_topic_return_does_not_guess_or_start_searches(self):
        llm, search = FakeLLM(), Mock()
        result = LiteraryAssistant(llm, search).reply('Volvamos a lo de antes', [],
            topic_context={'ambiguous_topic_return': True})
        self.assertEqual(result.status, 'clarification')
        self.assertEqual(llm.calls, 0)
        search.assert_not_called()

    def test_full_inverted_author_name_can_bind_the_same_title(self):
        book = {**DUNE, 'title': 'The Book of Tea', 'author': 'Okakura Kakuzō'}
        page = {'kind': 'web', 'title': book['title'], 'author': 'Fuente web',
                'identity_text': 'The Book of Tea is a book by Kakuzō Okakura.'}
        self.assertTrue(same_work(page, book))
        self.assertTrue(same_work({**book, 'author': 'Kakuzō Okakura'}, book))
        self.assertFalse(same_work({**book, 'title': 'Ideals of the East'}, book))
        self.assertFalse(same_work({**page, 'identity_text': 'The Book of Tea by Okakura.'}, book))

    def test_reordered_names_require_every_name_not_a_shared_surname(self):
        self.assertTrue(same_author_name('Herbert, Frank', 'Frank Herbert'))
        for left, right in [('Joly', 'Henri L. Joly'), ('Frank Herbert', 'Brian Herbert'),
                            ('Michael J. Seth', 'Michael K. Seth'), ('Fuente web', 'Fuente web')]:
            self.assertFalse(same_author_name(left, right))

    def test_same_author_queries_the_verified_author_and_excludes_previous_work(self):
        draft = {'status': 'answer', 'text': 'Puedes seguir con El mesías de Dune, de Frank Herbert.',
                 'basis': 'sources', 'citations': [1], 'needs_web': False,
                 'books': [{'title': MESSIAH['title'], 'author': MESSIAH['author'], 'source_id': 1}]}
        llm = FakeLLM(route={**ROUTE, 'intent': 'analysis', 'followup': True,
                             'candidates': [{'title': DUNE['title'], 'author': DUNE['author']}]}, answer=draft)
        search = Mock(return_value=[DUNE, PAPELUCHO, MESSIAH])
        bot = LiteraryAssistant(llm, search, require_book_sources=True)
        result = bot.reply('Otro del mismo autor', accepted(DUNE))
        self.assertEqual(result.status, 'answered', result.diagnostics)
        self.assertEqual(search.call_args.args[0], 'inauthor:"Frank Herbert"')
        self.assertEqual([s['title'] for s in result.sources], [MESSIAH['title']])
        self.assertEqual(result.intent, 'recommend')

    def test_multiple_authors_require_a_reference_before_searching(self):
        llm, search = FakeLLM(), Mock()
        result = LiteraryAssistant(llm, search, research_enabled=True).reply(
            'Otro del mismo autor', accepted(DUNE, PAPELUCHO))
        self.assertEqual(result.status, 'clarification')
        self.assertEqual(llm.calls, 0)
        search.assert_not_called()

    def test_similar_recommendation_uses_received_subjects(self):
        draft = {'status': 'answer', 'text': 'El mesías de Dune, de Frank Herbert.',
                 'basis': 'sources', 'citations': [1], 'needs_web': False,
                 'books': [{'title': MESSIAH['title'], 'author': MESSIAH['author'], 'source_id': 1}]}
        llm = FakeLLM(route={**ROUTE, 'followup': True}, answer=draft)
        search = Mock(return_value=[{**MESSIAH, 'categories': ['Science fiction']}])
        result = LiteraryAssistant(llm, search, require_book_sources=True).reply(
            'Otro parecido', accepted(DUNE))
        self.assertEqual(result.status, 'answered', result.diagnostics)
        self.assertEqual(search.call_args.args[0], 'libros sobre Science fiction')
        self.assertEqual(result.diagnostics['recommendation_relation'], 'similar')
