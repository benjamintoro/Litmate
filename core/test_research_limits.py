"""Límites compartidos, finales desconocidos y frases recordadas sin citas falsas."""
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from .literary_sources import research_scope, reserve_search, reserve_page, account_research
from .literary_research import assess_evidence
from .literary_evidence import validate_evidence


class ResearchBoundaryTests(SimpleTestCase):
    def test_nested_fast_path_and_model_share_two_searches_three_pages(self):
        with research_scope(2, 15, 3):
            self.assertGreater(reserve_search(), 0)
            self.assertTrue(reserve_page())
            with research_scope(2, 15, 3):
                self.assertGreater(reserve_search(), 0)
                self.assertTrue(reserve_page())
                self.assertTrue(reserve_page())
            self.assertEqual(reserve_search(), 0)
            self.assertFalse(reserve_page())
        with research_scope():
            self.assertGreater(reserve_search(), 0)

    def test_model_time_is_not_charged_but_external_time_consumes_budget(self):
        with research_scope(2, 15):
            self.assertEqual(reserve_search(), 15)
            account_research(15)
            self.assertEqual(reserve_search(), 0)

    def test_general_event_does_not_verify_the_ending(self):
        book = {'title': 'Un libro', 'author': 'Una autora', 'kind': 'book', 'source': 'Catálogo LitMate'}
        text = 'Det convive con Papelucho y su amistad trae problemas cotidianos.'
        source = {**book, 'description': text, 'literary_facts': [{'topic': 'events',
                  'subject': 'Det', 'evidence': text}]}
        self.assertTrue(assess_evidence('¿Qué sucede con Det?', [source], [book], 'analysis')['sufficient'])
        ending = assess_evidence('¿Qué sucede con Det al final?', [source], [book], 'analysis')
        self.assertFalse(ending['sufficient'])
        self.assertIn('ending', ending['missing'])

    def test_single_quote_cannot_hide_an_invented_literal_passage(self):
        source = {'id': 1, 'kind': 'web', 'description': 'Una explicación diferente.'}
        draft = {'status': 'answer', 'basis': 'sources', 'books': [], 'citations': [1],
                 'text': "El libro afirma 'esta frase nunca estuvo en la fuente'."}
        with self.assertRaises(ValueError):
            validate_evidence(draft, [source], 'Identifica la obra')

    def test_identification_summary_does_not_establish_a_novel_quote(self):
        phrase = 'todos los animales son iguales'
        source = {'id': 1, 'kind': 'web', 'description': 'La idea de que ' + phrase + ' se recuerda en esta obra.',
                  'read_mode': 'resumen factual original con procedencia; no texto de la novela'}
        draft = {'status': 'answer', 'basis': 'sources', 'books': [], 'citations': [1],
                 'text': "El libro dice literalmente '" + phrase + "'."}
        with self.assertRaises(ValueError):
            validate_evidence(draft, [source], 'Identifica el libro')
        draft['text'] = "Tu recuerdo de '" + phrase + "' permite identificar la obra; es una paráfrasis, sin edición confirmada."
        validate_evidence(draft, [source], 'Identifica el libro')


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                     'LOCATION': 'wikipedia-shared-reading-budget'}},
                   LITMATE_AI_USE_SEARXNG=True, LITMATE_RESEARCH_MAX_PAGES=3)
class WikipediaReadingBudgetTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.query = '"Papelucho y el marciano" Marcela Paz personajes'
        self.intro = {'query': {'pages': {'123': {
            'pageid': 123, 'title': 'Papelucho y el marciano',
            'fullurl': 'https://es.wikipedia.org/wiki/Papelucho_y_el_marciano',
            'extract': 'Papelucho y el marciano es una obra de Marcela Paz.',
        }}}}
        self.article = {'query': {'pages': {'123': {
            **self.intro['query']['pages']['123'],
            'extract': '== Personajes ==\nPapelucho: un niño curioso.\nDet: su amigo marciano.',
        }}}}

    def test_official_article_and_html_pages_share_three_reads(self):
        from .literary_search import _retrieve_web

        snippets = [{'title': 'Papelucho y el marciano: ficha ' + str(index),
                     'author': 'Fuente web', 'kind': 'web', 'source': 'DuckDuckGo',
                     'url': 'https://literaturasm.cl/ficha-' + str(index),
                     'description': 'Ficha de Marcela Paz y sus personajes número ' + str(index),
                     'read_mode': 'fragmento del buscador'} for index in range(3)]
        extracted = {'status': 'ok', 'description': 'Papelucho y Det, personajes de la obra de Marcela Paz.',
                     'title': 'Papelucho y el marciano'}
        with research_scope(2, 15, 3), \
                patch('core.literary_search.search_duckduckgo', return_value=snippets), \
                patch('core.literary_search.read_json_url', side_effect=[self.intro, self.article]) as api, \
                patch('core.literary_search.read_public_page', return_value=extracted) as html:
            results = _retrieve_web(self.query)
            self.assertEqual(api.call_count, 2)
            self.assertEqual(html.call_count, 2)
            self.assertFalse(reserve_page())
        self.assertTrue(any(item.get('read_mode') == 'pasaje de sección de artículo público'
                            for item in results))

    def test_exhausted_html_budget_preserves_wikipedia_intro_without_full_read(self):
        from .literary_search import search_wikipedia

        with research_scope(2, 15, 3), \
                patch('core.literary_search.read_json_url', return_value=self.intro) as api:
            for _ in range(3):
                self.assertTrue(reserve_page())
            results = search_wikipedia(self.query)
        self.assertEqual(api.call_count, 1)
        self.assertEqual(results[0]['read_mode'], 'extracto de introducción')
        self.assertEqual(results[0]['description'], self.intro['query']['pages']['123']['extract'])
        self.assertEqual(results[0]['character_facts'], [])

    def test_bibliographic_intro_does_not_consume_a_page_read(self):
        from .literary_search import search_wikipedia

        with research_scope(2, 15, 1), \
                patch('core.literary_search.read_json_url', return_value=self.intro) as api:
            results = search_wikipedia('Papelucho y el marciano Marcela Paz')
            self.assertTrue(reserve_page())
        self.assertEqual(api.call_count, 1)
        self.assertEqual(results[0]['read_mode'], 'extracto de introducción')
