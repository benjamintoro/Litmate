"""Identidad, profundidad y personajes: fuentes sintéticas, sin casos especiales."""
from django.test import SimpleTestCase
from .test_narrative_answers import BOOK, PAGE


class LiteraryDepthTests(SimpleTestCase):
    def test_apposition_stops_before_a_parenthetical_return_to_another_subject(self):
        from .literary_web import narrative_character_facts
        facts = narrative_character_facts('Ión busca a Palas Celeste, hija de Zeus — es capaz de escapar de la isla.')
        self.assertEqual(facts[0]['role'], 'hija de Zeus')

    def test_invisible_reference_separator_does_not_join_two_factual_sentences(self):
        from .literary_quality import factual_statements
        self.assertEqual(factual_statements('Ión busca la isla.\u200b Celia dirige el puerto.'),
                         ['Ión busca la isla.', 'Celia dirige el puerto.'])

    def test_compound_query_does_not_discard_a_relevant_spanish_title_for_english(self):
        from unittest.mock import patch
        from django.core.cache import cache
        from .literary_search import search_wikipedia
        cache.clear()
        with patch('core.literary_search._search_wikipedia', return_value=[{**PAGE, 'title': 'Viaje Cosmico'}]) as fetch:
            search_wikipedia('"ViajeCosmico" argumento')
        fetch.assert_called_once()

    def test_plot_section_is_not_replaced_by_its_short_introduction(self):
        from .ai_narrative_answers import bound_sources, request_for
        intro = 'Cuaderno lunar es una novela de Ana Robles que narra la búsqueda de su hermano.'
        page = {**PAGE, 'identity_text': intro}
        bound = bound_sources(request_for('Dime la trama de Cuaderno lunar'), [BOOK, page])
        body = next(source['description'] for source in bound if source['kind'] == 'web')
        self.assertIn('estación lunar', body)
        self.assertIn('capitán', body)

    def test_epic_poem_with_a_catalogue_article_variant_uses_its_own_identity(self):
        from .ai_narrative_answers import bound_sources, request_for
        book = {**BOOK, 'title': 'La travesía', 'author': 'Asterio'}
        page = {**PAGE, 'title': 'Travesía', 'identity_text':
                'La Travesía es un poema épico atribuido a Asterio.',
                'description': '== Argumento == La obra narra el regreso de Ión a su isla.'}
        sources = bound_sources(request_for('Dime la trama de La travesía'), [book, page])
        self.assertTrue(any(source['kind'] == 'web' for source in sources))
        # A query article variant does not merge catalogue records.
        self.assertFalse(any(source['kind'] == 'book' for source in sources))

    def test_single_word_attributed_author_and_epic_identity_are_preserved(self):
        from .literary_identity import _identity_author
        page = {**PAGE, 'title': 'Travesía', 'identity_text': 'Travesía es un poema épico atribuido a Asterio.'}
        self.assertEqual(_identity_author(page), 'Asterio')

    def test_linked_appositions_in_a_plot_prove_character_roles_without_a_character_heading(self):
        from .literary_web import character_content
        html = '''<h1>Travesía</h1><h2>Argumento</h2>
          <p><a href="/wiki/Ion">Ión</a>, un navegante que busca a su familia, llega al puerto.</p>
          <p><a href="/wiki/Celia">Celia</a>, la reina de la isla, recibe a los viajeros.</p>
          <p><a href="/wiki/Puerto">Puerto</a>, una ciudad del norte, tiene una muralla.</p>
          <h2>Adaptaciones</h2><p><a href="/wiki/Lia">Lía</a>, una capitana inventada para la película, conduce la nave.</p>'''
        result = character_content(html, title='Travesía', context='Personajes de Travesía')
        self.assertEqual({fact['name'] for fact in result['character_facts']}, {'Ión', 'Celia'})
        for fact in result['character_facts']:
            self.assertIn(fact['name'], fact['evidence'])
            self.assertIn(fact['role'], fact['evidence'])

    def test_linked_mentions_and_negated_roles_do_not_become_character_facts(self):
        from .literary_web import character_content
        html = '''<h2>Argumento</h2><p><a href="/wiki/Ion">Ión</a> vio a una reina.</p>
          <p><a href="/wiki/Celia">Celia</a> no es la reina de la isla.</p>'''
        self.assertEqual(character_content(html, title='Travesía')['character_facts'], [])

    def test_introductory_nominal_phrase_keeps_the_hero_without_inferring_a_role(self):
        from .literary_web import character_content
        html = '<p>La obra narra el regreso del héroe marino <a href="/wiki/Ion">Ión</a> a su hogar.</p>'
        result = character_content(html, title='Travesía', context='Travesía es un poema épico.')
        self.assertEqual(result['character_facts'][0]['name'], 'Ión')
        self.assertEqual(result['character_facts'][0]['role'], 'héroe marino')

    def test_stored_plot_apposition_and_a_bound_profile_remain_recoverable(self):
        from .ai_character_answers import answer_from_sources, request_for
        plot = {**PAGE, 'description': '== Argumento == Bruno Salas, un estudiante de ciencias naturales, '
                'investiga el laboratorio abandonado.'}
        profile = {**PAGE, 'title': 'Guardián lunar', 'url': 'https://es.wikipedia.org/wiki/Guardian_lunar',
                   'work_title': BOOK['title'], 'work_author': BOOK['author'], 'work_binding_verified': True,
                   'identity_text': '', 'description': 'El Guardián lunar es un personaje de ficción de la novela '
                   'Cuaderno lunar, de Ana Robles.'}
        result = answer_from_sources('Dime los personajes de Cuaderno lunar',
            request_for('Dime los personajes de Cuaderno lunar'), [BOOK, plot, profile])
        self.assertIsNotNone(result)
        self.assertIn('Bruno Salas', result.text)
        self.assertIn('Guardián lunar', result.text)

    def test_shortened_compound_surname_is_not_presented_as_another_character(self):
        from .ai_character_answers import answer_from_sources, request_for
        facts = [{'name': 'Bruno Del Campo', 'role': 'un médico experto en enfermedades extrañas'},
                 {'name': 'Del Campo', 'role': 'un médico de la ciudad'},
                 {'name': 'Elena Del Campo', 'role': 'una capitana que protege la estación'}]
        page = {**PAGE, 'description': '\n'.join(f['name'] + ': '+f['role']+'.' for f in facts), 'character_facts': facts}
        result = answer_from_sources('Dime los personajes de Cuaderno lunar',
            request_for('Dime los personajes de Cuaderno lunar'), [BOOK, page])
        self.assertIsNotNone(result)
        self.assertIn('**Bruno Del Campo**', result.text)
        self.assertIn('**Elena Del Campo**', result.text)
        self.assertNotIn('**Del Campo**', result.text)
        fragments = [{**page, 'evidence_scope': 'summary', 'character_facts': [facts[0], facts[2]]},
                     {**page, 'evidence_scope': 'characters', 'character_facts': [facts[1]],
                      'description': facts[1]['name']+': '+facts[1]['role']+'.'}]
        result = answer_from_sources('Dime los personajes de Cuaderno lunar',
            request_for('Dime los personajes de Cuaderno lunar'), [BOOK, *fragments])
        self.assertIsNotNone(result)
        self.assertNotIn('**Del Campo**', result.text)

    def film(self):
        title = 'Viaje Cósmico'
        url = 'https://es.wikipedia.org/wiki/Viaje_cosmico'
        return {**PAGE, 'title': title, 'url': url,
            'identity_text': 'Viaje Cósmico es una película dirigida por Elena Sol. '
                             'Está basada parcialmente en la novela de Ana Robles ¿Dónde está la luna?',
            'attribution': {**PAGE['attribution'], 'title': title, 'url': url}}

    def test_epic_work_section_remains_plot_evidence_instead_of_becoming_intro(self):
        from .ai_narrative_answers import bound_sources, request_for, direct_answer
        page = {**PAGE, 'description': '== La obra == Ana viaja a la luna para buscar a su hermano. '
                'Bruno protege la nave mientras ella explora la estación abandonada.'}
        request = request_for('Dime la trama de Cuaderno lunar')
        bound = bound_sources(request, [BOOK, page])
        self.assertTrue(any('== La obra ==' in source['description'] for source in bound))
        result = direct_answer('Dime la trama de Cuaderno lunar', request, bound)
        self.assertIsNotNone(result)
        self.assertIn('Bruno protege', result.text)

    def test_publication_notes_do_not_stop_retrieval_of_a_more_complete_plot(self):
        from django.test import override_settings
        from unittest.mock import patch
        from .ai_narrative_answers import retrieve_sources, request_for
        short = {**PAGE, 'description': 'Cuaderno lunar es una novela de Ana Robles. '
            'Fue publicada en 1920 por una editorial local. Narra un viaje a la luna para buscar a un hermano.'}
        with override_settings(LITMATE_AI_USE_WEB=True, LITMATE_AI_USE_OPENLIBRARY=False,
                               LITMATE_AI_USE_WIKIDATA=False), \
                patch('core.ai_quick_answers.quick_knowledge_sources', return_value=[BOOK, short]), \
                patch('core.ai_library_router.sources_for_request', return_value=[]), \
                patch('core.literary_search.search_wikipedia', return_value=[PAGE]) as wiki, \
                patch('core.ai_persistent_router.persist_sources'):
            sources = retrieve_sources('Dime la trama de Cuaderno lunar', request_for('Dime la trama de Cuaderno lunar'), [])
        wiki.assert_called_once()
        self.assertTrue(any('== Argumento ==' in source['description'] for source in sources))

    def test_current_section_is_used_instead_of_the_first_cached_short_intro(self):
        from .ai_narrative_answers import direct_answer, request_for
        intro = {**PAGE, 'memory_verified': True, 'policy': 'wikipedia-cc-by-sa-4.0-v1',
                 'evidence_scope': 'summary', 'description': 'Narra la historia de una joven que viaja a la luna para buscar a su hermano.'}
        result = direct_answer('Dime la trama de Cuaderno lunar', request_for('Dime la trama de Cuaderno lunar'),
                               [BOOK, intro, PAGE])
        self.assertIsNotNone(result)
        self.assertIn('Bruno', result.text)

    def test_independent_work_page_resolves_conflicting_catalogue_author_labels_without_merging(self):
        from .ai_narrative_answers import bound_sources, request_for
        longer = {**BOOK, 'author': 'Ana María Robles'}
        req = {**request_for('Dime la trama de Cuaderno lunar'), 'targets': [longer]}
        result = bound_sources(req, [longer, BOOK, PAGE])
        self.assertTrue(any(source['kind'] == 'web' for source in result))
        self.assertEqual({s['author'] for s in result if s['kind'] == 'book'}, {BOOK['author']})
        self.assertEqual(longer['author'], 'Ana María Robles')
        # An explicit contrary author is not silently replaced by the other book.
        req['author_hint'] = longer['author']
        self.assertFalse(any(s['kind'] == 'web' for s in bound_sources(req, [longer, BOOK, PAGE])))

    def test_film_relation_is_not_a_book_alias_and_preserves_partial_adaptation(self):
        from .ai_narrative_answers import adaptation_answer, request_for
        result = adaptation_answer('Dime la trama de ViajeCósmico', request_for('Dime la trama de ViajeCósmico'), [self.film()])
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'clarification')
        self.assertIn('basada parcialmente', result.text)
        self.assertIn('¿Dónde está la luna?', result.text)
        self.assertEqual(result.books, [])
        self.assertTrue(result.diagnostics['audit']['claims'])

    def test_explicit_book_request_does_not_silently_switch_to_film(self):
        from .ai_narrative_answers import adaptation_answer, request_for
        self.assertIsNone(adaptation_answer('Dime la trama del libro Viaje Cósmico',
            request_for('Dime la trama del libro Viaje Cósmico'), [self.film()]))

    def test_film_without_a_literary_connection_does_not_invent_one(self):
        from .ai_narrative_answers import adaptation_answer, request_for
        page = self.film(); page['identity_text'] = page['identity_text'].split(' Está')[0]
        result = adaptation_answer('Dime la trama de Viaje Cósmico', request_for('Dime la trama de Viaje Cósmico'), [page])
        self.assertIsNotNone(result)
        self.assertFalse(result.diagnostics['adaptation_relation'])
        self.assertNotIn('basada', result.text)
