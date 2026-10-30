"""Datos sintéticos: traducción de presentación, nunca nueva evidencia."""
from copy import deepcopy
from unittest.mock import Mock
from django.test import SimpleTestCase
from django.core.cache import cache
from .literary_ai import ChatResult
from .ai_presentation import build_book_cards


class PresentationLanguageTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.book = {'id': 1, 'kind': 'book', 'title': 'A History of Medieval Europe',
            'author': 'R. H. C. Davis', 'description': 'An introduction to early medieval history.',
            'synopsis': 'An introduction to early medieval history.', 'language': 'en',
            'url': 'https://openlibrary.org/works/OL1W',
            'image_url': 'https://covers.openlibrary.org/b/id/1-M.jpg', 'isbn': '9780000000002'}

    def result(self, description=None):
        source = dict(self.book)
        if description is not None:
            source['description'] = source['synopsis'] = description
        return ChatResult('**' + source['title'] + ' — ' + source['author'] + '**:\n\n' +
            source['synopsis'] + '\n\nFuentes de las fichas:\n' + source['url'],
            'answered', True, [source], [{'title': source['title'], 'author': source['author'],
                                        'source_id': 1}], 'sources', 'recommend')

    def translator(self):
        def run(stage, prompt, data, model):
            if stage == 'language_verify':
                return {'checks': {key: True for key in data['translations']}}
            return {'translations': {key: text.replace('An introduction to early medieval history.',
                'Una introducción a la historia medieval temprana.').replace(
                'The novel follows a young traveller.', 'La novela sigue a un joven viajero.')
                for key, text in data['texts'].items()}}
        return Mock(side_effect=run)

    def test_english_description_and_body_are_spanish_original_evidence_untouched(self):
        from .literary_presentation_language import localize_result
        result = self.result()
        original = deepcopy(result.sources)
        localize_result(result, 'Dime libros sobre historia medieval', self.translator(), 'local')
        self.assertIn('Una introducción', result.text)
        self.assertNotIn('An introduction', result.text)
        self.assertNotIn('Fuentes de las fichas', result.text)
        self.assertEqual(result.sources, original)
        self.assertEqual(build_book_cards(result)[0]['synopsis'], 'Una introducción a la historia medieval temprana.')

    def test_spanish_description_needs_no_model(self):
        from .literary_presentation_language import localize_result
        model = self.translator()
        result = self.result('La obra explica la historia medieval y sus cambios sociales.')
        localize_result(result, 'Recomiéndame historia', model, 'local')
        model.assert_not_called()
        self.assertIn('sus cambios sociales', result.text)

    def test_original_title_author_cover_and_store_buttons_survive(self):
        from .literary_presentation_language import localize_result
        result = self.result()
        localize_result(result, 'Recomiéndame historia', self.translator(), 'local')
        card = build_book_cards(result)[0]
        self.assertEqual(card['title'], self.book['title'])
        self.assertEqual(card['author'], self.book['author'])
        self.assertEqual(card['image_url'], self.book['image_url'])
        self.assertEqual([link['label'] for link in card['links']],
                         ['Google Books', 'Open Library', 'Amazon', 'Buscalibre'])

    def test_verified_spanish_edition_is_kept_without_inventing_a_translation(self):
        from .literary_presentation_language import localize_result
        from .ai_quick_answers import _bundled
        # La identidad española viene del catálogo verificado existente.
        source = {**next(book for book in _bundled() if book['title'] == 'El principito'), 'id': 1}
        result = ChatResult('**El principito**: ' + source['synopsis'], 'answered', True,
            [source], [{'title': source['title'], 'author': source['author'], 'source_id': 1}])
        model = self.translator()
        localize_result(result, 'Dime libros', model, 'local')
        self.assertEqual(build_book_cards(result)[0]['title'], 'El principito')
        self.assertEqual(build_book_cards(result)[0]['author'], source['author'])
        model.assert_not_called()

    def test_foreign_narrative_keeps_source_and_literal_quote(self):
        from .literary_presentation_language import localize_result
        result = self.result()
        result.intent = 'summary'
        result.text = 'The novel follows a young traveller.\n\n«The original quotation»\n\nFuente: ' + self.book['url']
        localize_result(result, 'Dime la trama', self.translator(), 'local')
        self.assertIn('La novela sigue', result.text)
        self.assertIn('«The original quotation»', result.text)
        self.assertIn('Fuente: ' + self.book['url'], result.text)

    def test_explicit_english_is_not_confused_with_book_language(self):
        from .literary_language import response_language
        from .literary_presentation_language import localize_result
        self.assertEqual(response_language('Recomiéndame libros en inglés'), 'es')
        self.assertEqual(response_language('Responde en inglés: recomiéndame historia'), 'en')
        result, model = self.result(), self.translator()
        localize_result(result, 'Answer in English: recommend history books', model, 'local')
        model.assert_not_called()
        self.assertIn('An introduction', result.text)

    def test_public_description_cache_does_not_cache_private_answers(self):
        from .literary_presentation_language import localize_result
        model = self.translator()
        for _ in range(2):
            result = self.result()
            result.text = 'Aquí tienes una lectura para explorar.'
            localize_result(result, 'Dime libros', model, 'local')
        self.assertEqual(model.call_count, 2)  # Traducción y verificación, sólo primera ficha.

    def test_failed_fidelity_check_never_publishes_invented_spanish(self):
        from .literary_presentation_language import localize_result
        model = Mock(side_effect=[{'translations': {'card0': 'Un extraterrestre inventado.'}},
                                 {'checks': {'card0': False}}])
        result = self.result()
        result.text = 'Aquí tienes una lectura.'
        localize_result(result, 'Dime libros', model, 'local')
        self.assertNotIn('extraterrestre', str(build_book_cards(result)))
        self.assertEqual(result.sources[0]['synopsis'], self.book['synopsis'])

    def test_other_genres_and_languages_are_detected_without_using_edition_language(self):
        from .literary_language import narrative_language
        cases = [('The novel follows a young traveller.', 'en'),
                 ('The book explores the history of painting and its artists.', 'en'),
                 ('Le roman raconte une histoire avec ses personnages.', 'fr'),
                 ('La novela cuenta la historia de una joven viajera.', 'es'),
                 ('Podemos conversar un rato. ¿Qué te gustaría contarme de tu día?', 'es'),
                 ('La obra estudia los cambios sociales del periodo.', 'es')]
        for text, language in cases:
            with self.subTest(text=text):
                self.assertEqual(narrative_language(text), language)

    def test_translation_cannot_change_numbers_or_protected_names(self):
        from .literary_presentation_language import _protect, _valid_translation
        text, saved = _protect('The novel was published in 1954 by Ada Robles.', ['Ada Robles'])
        self.assertFalse(_valid_translation(text, 'La novela se publicó en 2001.', saved, 'es'))

    def test_explicit_english_translates_spanish_and_keeps_original_title(self):
        from .literary_presentation_language import localize_result
        result = self.result('La novela narra un viaje y sus encuentros.')
        def run(stage, prompt, data, model):
            if stage == 'language_verify':
                return {'checks': {key: True for key in data['translations']}}
            return {'translations': {key: text.replace('La novela narra un viaje y sus encuentros.',
                'The novel tells the story of a journey and its encounters.') for key, text in data['texts'].items()}}
        localize_result(result, 'Responde en inglés: dime la trama', run, 'local')
        self.assertIn('The novel tells', result.text)
        self.assertEqual(build_book_cards(result)[0]['title'], self.book['title'])

    def test_original_audit_and_narrative_links_are_preserved(self):
        from .literary_presentation_language import localize_result
        result = self.result()
        result.intent = 'summary'
        result.diagnostics['audit'] = {'claims': [{'evidence': self.book['description']}]}
        audit = deepcopy(result.diagnostics['audit'])
        localize_result(result, 'Dime la trama', self.translator(), 'local')
        self.assertEqual(result.diagnostics['audit'], audit)
        self.assertIn(self.book['url'], result.text)
        self.assertIn('Fuentes:', result.text)

    def test_ollama_language_stage_uses_translation_schema_not_router_schema(self):
        from unittest.mock import patch
        from .local_llm import OllamaJSON
        from .test_local_ai import SHOW, response
        client = OllamaJSON()
        with patch('core.local_llm.read_json_url', side_effect=[SHOW,
                response({'translations': {'card0': 'La novela cuenta un viaje.'}})]) as fetch:
            result = client('language_translate', 'Traduce',
                {'target_language': 'español', 'texts': {'card0': 'The novel tells a journey.'}}, 'local-test')
        self.assertIn('card0', result['translations'])
        self.assertEqual(fetch.call_args.kwargs['payload']['format']['required'], ['translations'])

    def test_verified_terminology_is_preserved_for_any_work_without_translating_titles(self):
        from .literary_presentation_language import _protect
        for description in ('The history covers the High Middle Ages.',
                            'The novel is set in the Late Middle Ages.'):
            text, protected = _protect(description, [])
            self.assertNotIn('Middle Ages', text)
            self.assertTrue(set(protected.values()) & {'Plena Edad Media', 'Baja Edad Media'})
        text, protected = _protect('High Middle Ages', ['High Middle Ages'])
        self.assertEqual(list(protected.values()), ['High Middle Ages'])

    def test_localized_cards_still_validate_identity_and_link_security(self):
        from .literary_presentation_language import localize_result
        result = self.result()
        localize_result(result, 'Dime libros', self.translator(), 'local')
        result.sources[0]['url'] = 'javascript:alert(1)'
        self.assertFalse(any(link['url'].startswith('javascript:') for link in build_book_cards(result)[0]['links']))
        result.sources[0]['author'] = 'Otra identidad'
        self.assertEqual(build_book_cards(result), [])

    def test_explicit_language_is_not_read_from_a_quoted_book_title(self):
        from .literary_language import response_language
        self.assertEqual(response_language('Dime libros titulados «Responde en inglés»'), 'es')
