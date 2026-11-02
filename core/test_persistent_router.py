"""Recuperación por evidencia, independiente de Internet/Ollama en estas pruebas."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings

from .ai_persistent_router import _work_web_pages, indexed_answer, research_answer
from .ai_public_details import character_answer
from .ai_quick_answers import catalogue_lookup_answer
from .literary_ai import canonical_sources
from .literary_memory import remember_evidence
from .literary_search import _wikipedia_storage_metadata


BOOK = {'kind': 'book', 'title': 'Orgullo y prejuicio', 'author': 'Jane Austen',
        'description': 'Orgullo y prejuicio, de Jane Austen.', 'source': 'Open Library',
        'url': 'https://openlibrary.org/works/OL123W'}

NANA_BOOK = {'kind': 'book', 'title': 'Nana', 'author': 'Émile Zola',
             'description': 'Nana, de Émile Zola.', 'source': 'Open Library',
             'url': 'https://openlibrary.org/works/OL456W'}

NANA_PAGE = {'kind': 'web', 'title': 'Nana (novela)', 'author': 'Fuente web',
             'description': 'Nana es una novela de Émile Zola. '
                            'Nana Coupeau: protagonista, actriz y cortesana. '
                            'Muffat: conde que se obsesiona con Nana.',
             'identity_text': 'Nana (novela) de Émile Zola. Nana Coupeau: protagonista.',
             'character_facts': [
                 {'name': 'Nana Coupeau', 'role': 'protagonista, actriz y cortesana'},
                 {'name': 'Muffat', 'role': 'conde que se obsesiona con Nana'}],
             'url': 'https://es.wikipedia.org/wiki/Nana_(novela)', 'source': 'Wikipedia',
             'read_mode': 'pasaje de sección de artículo público'}

ROSE_PAGE = {'kind': 'web', 'title': 'El nombre de la rosa', 'author': 'Fuente web',
             'description': 'El nombre de la rosa es una novela de Umberto Eco. '
                            'La historia sigue a Guillermo de Baskerville en una abadía medieval.',
             'url': 'https://es.wikipedia.org/wiki/El_nombre_de_la_rosa', 'source': 'Wikipedia',
             'read_mode': 'pasaje de sección de artículo público'}


class PersistentRouterTests(SimpleTestCase):
    def test_title_with_y_uses_verified_authorship_route(self):
        search = lambda query: [dict(BOOK)]
        result = catalogue_lookup_answer('¿Quién escribió Orgullo y prejuicio?', [], search)
        self.assertIsNotNone(result)
        self.assertIn('Jane Austen', result.text)

    def test_author_question_uses_structured_authorship_over_messy_editions(self):
        translated = {**BOOK, 'author': 'Lourdes Íñiguez Barrena, Jane Austen, Mónica Armiño',
                      'url': 'https://openlibrary.org/works/OL34810920W'}
        translator = {**BOOK, 'author': 'Roser Vilagrassa',
                      'url': 'https://openlibrary.org/works/OL17505350W'}
        wikidata = {**BOOK, 'author': 'Jane Austen', 'source': 'Wikidata',
                    'url': 'https://www.wikidata.org/wiki/Q170583',
                    'description': 'Orgullo y prejuicio, de Jane Austen.'}
        result = catalogue_lookup_answer('¿Quién escribió Orgullo y prejuicio?', [],
                                        lambda query: [translated, translator, wikidata])
        self.assertIsNotNone(result)
        self.assertIn('Jane Austen', result.text)
        self.assertNotIn('Roser Vilagrassa', result.text)

    def test_title_conjunction_does_not_hide_a_second_task(self):
        result = catalogue_lookup_answer('¿Quién escribió Orgullo y prejuicio y dime sus personajes?', [],
                                        lambda query: [dict(BOOK)])
        self.assertIsNone(result)

    def test_comparison_keeps_the_full_pipeline(self):
        message = 'Compara el protagonista de El túnel con el de Madame Bovary.'
        self.assertIsNone(indexed_answer(message, []))
        self.assertIsNone(research_answer(message, []))

    def test_public_metadata_survives_restart_and_answers_without_http(self):
        with TemporaryDirectory() as temporary, override_settings(
                LITMATE_LITERARY_MEMORY_DB=Path(temporary) / 'memory.sqlite3'):
            self.assertEqual(remember_evidence([BOOK], [BOOK])['sources'], 1)
            with patch('core.literary_search.search_openlibrary') as remote:
                result = indexed_answer('¿Quién escribió Orgullo y prejuicio?', [])
            self.assertIsNotNone(result)
            self.assertIn('Jane Austen', result.text)
            remote.assert_not_called()

    def test_metadata_does_not_answer_a_character_question(self):
        with TemporaryDirectory() as temporary, override_settings(
                LITMATE_LITERARY_MEMORY_DB=Path(temporary) / 'memory.sqlite3'):
            remember_evidence([BOOK], [BOOK])
            self.assertIsNone(indexed_answer('Dime los personajes de Orgullo y prejuicio', []))

    def test_metadata_does_not_replace_original_synopsis_or_its_provenance(self):
        from .ai_quick_answers import quick_knowledge_sources
        book = {**BOOK, 'title': 'El principito', 'author': 'Antoine de Saint-Exupéry'}
        with TemporaryDirectory() as temporary, override_settings(
                LITMATE_LITERARY_MEMORY_DB=Path(temporary) / 'memory.sqlite3'):
            remember_evidence([book], [book])
            result = indexed_answer('¿De qué trata El principito?', [])
            self.assertIsNotNone(result)
            self.assertIn('rosa', result.text.lower())
            for source in quick_knowledge_sources('El principito'):
                if 'rosa' in source['description'].lower():
                    self.assertNotEqual(source['url'], book['url'])

    def test_metadata_of_unknown_work_is_not_published_as_a_plot(self):
        with TemporaryDirectory() as temporary, override_settings(
                LITMATE_LITERARY_MEMORY_DB=Path(temporary) / 'memory.sqlite3'):
            remember_evidence([BOOK], [BOOK])
            self.assertIsNone(indexed_answer('¿De qué trata Orgullo y prejuicio?', []))

    @override_settings(LITMATE_AI_USE_OPENLIBRARY=True, LITMATE_AI_USE_WIKIDATA=False)
    def test_external_route_uses_catalogue_and_stops_without_llm(self):
        with TemporaryDirectory() as temporary, override_settings(
                LITMATE_LITERARY_MEMORY_DB=Path(temporary) / 'memory.sqlite3'), patch(
                'core.literary_search.search_openlibrary', return_value=[dict(BOOK)]) as search:
            result = research_answer('¿Quién escribió Orgullo y prejuicio?', [])
            self.assertIsNotNone(result)
            self.assertTrue(result.diagnostics['persistent_research_route'])
            search.assert_called_once_with('orgullo y prejuicio', details=False)

    @override_settings(LITMATE_AI_USE_WEB=True, LITMATE_AI_USE_OPENLIBRARY=True,
                       LITMATE_AI_USE_WIKIDATA=False)
    def test_summary_does_not_publish_fragments_without_bound_content(self):
        with TemporaryDirectory() as temporary, override_settings(
                LITMATE_LITERARY_MEMORY_DB=Path(temporary) / 'memory.sqlite3'), \
                patch('core.literary_search.search_openlibrary', return_value=[]), \
                patch('core.literary_search.search_wikipedia', return_value=[dict(ROSE_PAGE)]):
            result = research_answer('¿De qué trata El nombre de la rosa?', [])
        self.assertIsNone(result)

    @override_settings(LITMATE_AI_USE_WEB=True, LITMATE_AI_USE_OPENLIBRARY=True,
                       LITMATE_AI_USE_WIKIDATA=False)
    def test_protagonist_without_character_facts_does_not_publish_partial_references(self):
        page = {**ROSE_PAGE, 'title': 'Nana (novela)', 'url': 'https://es.wikipedia.org/wiki/Nana_(novela)',
                'identity_text': 'Nana (novela) de Émile Zola.',
                'description': 'Nana es una novela de Émile Zola sobre una joven que se convierte en cortesana.'}
        with TemporaryDirectory() as temporary, override_settings(
                LITMATE_LITERARY_MEMORY_DB=Path(temporary) / 'memory.sqlite3'), \
                patch('core.literary_search.search_openlibrary', return_value=[dict(NANA_BOOK)]), \
                patch('core.literary_search.search_wikipedia', return_value=[page]):
            result = research_answer('¿Quién es el protagonista de Nana?', [])
        self.assertIsNone(result)

    @override_settings(LITMATE_AI_USE_WEB=True, LITMATE_AI_USE_OPENLIBRARY=True,
                       LITMATE_AI_USE_WIKIDATA=False)
    def test_author_disambiguated_page_binds_to_the_requested_novel(self):
        decoy = {**ROSE_PAGE, 'title': 'Nana (novela)',
                 'url': 'https://es.wikipedia.org/wiki/Nana_(novela)',
                 'identity_text': 'Nana (2002) es una novela escrita por Chuck Palahniuk.',
                 'description': 'Nana es una novela de Chuck Palahniuk sobre un periodista.'}
        zola = {**ROSE_PAGE, 'title': 'Nana (Zola)',
                'url': 'https://es.wikipedia.org/wiki/Nana_(Zola)',
                'identity_text': 'Nana es una de las obras más representativas de Émile Zola.',
                'description': 'Nana es una novela de Émile Zola. El título hace referencia '
                               'al apelativo de la protagonista, Anne Coupeau.'}
        with TemporaryDirectory() as temporary, override_settings(
                LITMATE_LITERARY_MEMORY_DB=Path(temporary) / 'memory.sqlite3'), \
                patch('core.literary_search.search_openlibrary', return_value=[dict(NANA_BOOK)]), \
                patch('core.literary_search.search_wikipedia', return_value=[decoy, zola]):
            result = research_answer('¿Quién es el protagonista de Nana?', [])
        # Correct identity alone cannot manufacture a validated character role.
        self.assertIsNone(result)
        from .ai_narrative_answers import bound_sources, request_for
        bound = bound_sources(request_for('¿Quién es el protagonista de Nana?'),
                              [NANA_BOOK, decoy, zola])
        self.assertTrue(any('Anne Coupeau' in source['description'] for source in bound))
        self.assertFalse(any('Palahniuk' in source['description'] for source in bound))

    @override_settings(LITMATE_AI_USE_WEB=True, LITMATE_AI_USE_OPENLIBRARY=True,
                       LITMATE_AI_USE_WIKIDATA=False)
    def test_web_fallback_rejects_a_homonymous_work(self):
        foreign = SimpleNamespace(
            sources=[{'title': 'Nana (manga)', 'description': 'Nana, de Ai Yazawa.'}],
            diagnostics={})
        with TemporaryDirectory() as temporary, override_settings(
                LITMATE_LITERARY_MEMORY_DB=Path(temporary) / 'memory.sqlite3'), \
                patch('core.literary_search.search_openlibrary', return_value=[dict(NANA_BOOK)]), \
                patch('core.literary_search.search_wikipedia', return_value=[]), \
                patch('core.ai_quick_answers.web_reference_answer', return_value=foreign):
            result = research_answer('¿Quién es el protagonista de Nana?', [])
        self.assertIsNone(result)

    @override_settings(LITMATE_AI_USE_WEB=True, LITMATE_AI_USE_OPENLIBRARY=True,
                       LITMATE_AI_USE_WIKIDATA=False)
    def test_web_fallback_publishes_a_reference_bound_to_the_known_author(self):
        answer = SimpleNamespace(
            sources=[{'title': 'Nana (Zola)', 'description': 'Nana es una novela de Émile Zola.',
                      'identity_text': 'Nana es una novela de Émile Zola.',
                      'kind': 'web', 'url': 'https://es.wikipedia.org/wiki/Nana_(Zola)'}],
            diagnostics={})
        with TemporaryDirectory() as temporary, override_settings(
                LITMATE_LITERARY_MEMORY_DB=Path(temporary) / 'memory.sqlite3'), \
                patch('core.literary_search.search_openlibrary', return_value=[dict(NANA_BOOK)]), \
                patch('core.literary_search.search_wikipedia', return_value=[]), \
                patch('core.ai_quick_answers.web_reference_answer', return_value=answer) as web:
            result = research_answer('¿Quién es el protagonista de Nana?', [])
        self.assertIs(result, answer)
        self.assertTrue(result.diagnostics['persistent_research_route'])
        self.assertTrue(result.diagnostics['progressive_web_fallback'])
        self.assertIn('zola', web.call_args.kwargs['query'].lower())

    @override_settings(LITMATE_AI_USE_WEB=True, LITMATE_AI_USE_OPENLIBRARY=False,
                       LITMATE_AI_USE_WIKIDATA=True)
    def test_fallback_filters_a_homonymous_band_before_rendering_a_reference(self):
        band = {'title': 'Los Miserables (band) - Wikipedia', 'kind': 'web',
                'url': 'https://en.wikipedia.org/wiki/Los_Miserables_(band)',
                'description': 'Los Miserables is a Chilean punk rock band.'}
        with patch('core.ai_quick_answers.quick_knowledge_sources', return_value=[]), \
                patch('core.literary_wikidata.search_wikidata', return_value=[]), \
                patch('core.literary_search.search_wikipedia', return_value=[]), \
                patch('core.literary_search.retrieve_web', return_value=[band]):
            self.assertIsNone(research_answer('¿Quién es el protagonista de Los miserables?', []))

    def test_a_musical_adaptation_is_not_used_as_the_novel(self):
        novel = {'kind': 'web', 'title': 'Los miserables', 'author': 'Fuente web',
                 'description': 'Los miserables es una novela de Victor Hugo.',
                 'url': 'https://es.wikipedia.org/wiki/Los_miserables'}
        musical = {'kind': 'web', 'title': 'Los miserables (musical)', 'author': 'Fuente web',
                   'description': 'Los miserables es un musical basado en la novela de Victor Hugo.',
                   'url': 'https://es.wikipedia.org/wiki/Los_miserables_(musical)'}
        pages = _work_web_pages([novel, musical], 'Los miserables')
        self.assertEqual([page['title'] for page in pages], ['Los miserables'])

    def test_disambiguation_page_is_not_used_as_the_novel(self):
        page = {'kind': 'web', 'title': 'El túnel', 'author': 'Fuente web',
                'description': 'El túnel (novela), novela de Ernesto Sabato.',
                'identity_text': 'El túnel puede referirse a: El túnel (documental), '
                                 'El túnel (novela) y El túnel (película de 1952).',
                'url': 'https://es.wikipedia.org/wiki/El_t%C3%BAnel'}
        self.assertEqual(_work_web_pages([page], 'El túnel'), [])

    def test_protagonist_answer_uses_only_a_literal_role_from_the_same_work(self):
        result = character_answer('¿Quién es el protagonista de Nana?', [],
            lambda query: [dict(NANA_BOOK), dict(NANA_PAGE)],
            lambda query: [dict(NANA_PAGE)])
        self.assertIsNotNone(result)
        self.assertIn('Nana Coupeau', result.text)
        self.assertIn('protagonista', result.text)
        self.assertNotIn('Muffat', result.text)

    def test_protagonist_is_not_invented_when_the_source_only_lists_characters(self):
        page = {**NANA_PAGE, 'character_facts': [
            {'name': 'Nana Coupeau', 'role': 'actriz y cortesana'},
            {'name': 'Muffat', 'role': 'conde que se obsesiona con Nana'}]}
        self.assertIsNone(character_answer('¿Quién es el protagonista de Nana?', [],
            lambda query: [dict(NANA_BOOK), page], lambda query: [page]))

    def test_wikipedia_storage_requires_real_revision_and_keeps_attribution(self):
        self.assertEqual(_wikipedia_storage_metadata({'title': 'Obra', 'fullurl': 'https://es.wikipedia.org/wiki/Obra'}), {})
        metadata = _wikipedia_storage_metadata({'title': 'Obra', 'fullurl': 'https://es.wikipedia.org/wiki/Obra',
                                               'revisions': [{'revid': 12345}]})
        source = canonical_sources([{'title': 'Obra', 'author': 'Fuente web', 'kind': 'web',
                                     'source': 'Wikipedia', **metadata}])[0]
        self.assertEqual(source['attribution']['revision_id'], '12345')
        self.assertEqual(source['storage_policy'], 'wikipedia-cc-by-sa-4.0-v1')
