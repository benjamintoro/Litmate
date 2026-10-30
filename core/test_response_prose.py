"""Regresiones de presentación; evidencia sintética, no citas públicas reales."""
from unittest.mock import patch
from django.test import SimpleTestCase
from .test_narrative_answers import BOOK, PAGE


class ResponseProseTests(SimpleTestCase):
    def test_natural_question_recognizes_plot(self):
        from .ai_narrative_answers import request_for
        for title in ('Cuaderno lunar', 'Naruto', 'Historia del océano'):
            request = request_for('¿Cuál es la trama de ' + title + '?')
            self.assertIsNotNone(request)
            self.assertEqual(request['title'], title)

    def test_explicit_manga_keeps_format_and_title(self):
        from .ai_narrative_answers import request_for
        request = request_for('Dime la trama del manga Sendero azul')
        self.assertIsNotNone(request)
        self.assertEqual(request['title'], 'Sendero azul')
        self.assertEqual(request['format'], 'manga')

    def test_summary_fallback_uses_existing_audited_paragraph(self):
        from .ai_quick_answers import reference_answer
        result = reference_answer('Dime la trama de Cuaderno lunar', [BOOK, PAGE], intent='summary')
        self.assertIsNotNone(result)
        self.assertIn('Ana viaja', result.text)
        self.assertNotIn('Pasaje recuperado', result.text)
        self.assertNotIn('Esto es lo que dicen', result.text)
        self.assertTrue(result.diagnostics['audit']['claims'])

    def test_unverified_search_fragment_is_not_a_plot(self):
        from .ai_quick_answers import reference_answer
        page = {**PAGE, 'license': '', 'read_mode': 'fragmento del buscador'}
        self.assertIsNone(reference_answer('Dime la trama de Cuaderno lunar', [BOOK, page], intent='summary'))

    def test_failed_audit_cannot_be_replaced_by_raw_fragments(self):
        from .ai_quick_answers import reference_answer
        with patch('core.ai_narrative_answers.direct_answer', return_value=None):
            self.assertIsNone(reference_answer('Dime la trama de Cuaderno lunar', [BOOK, PAGE], intent='summary'))

    def test_character_fallback_does_not_claim_a_snippet_answers_the_question(self):
        from .ai_quick_answers import reference_answer
        self.assertIsNone(reference_answer('Dime los personajes de Cuaderno lunar', [BOOK, PAGE], intent='analysis'))

    def test_nonfiction_content_is_prose_not_a_fiction_template(self):
        from .ai_quick_answers import reference_answer
        book = {**BOOK, 'title': 'Historia del océano'}
        page = {**PAGE, 'title': book['title'],
                'identity_text': 'Historia del océano es un libro de Ana Robles.',
                'description': '== Contenido == La obra estudia las rutas comerciales del océano '
                               'y describe sus intercambios culturales.'}
        result = reference_answer('Dime el argumento de Historia del océano', [book, page], intent='summary')
        self.assertIsNotNone(result)
        self.assertIn('rutas comerciales', result.text)
        self.assertNotIn('Pasaje recuperado', result.text)

    def test_contradictory_sources_are_not_combined(self):
        from .ai_quick_answers import reference_answer
        self.assertIsNone(reference_answer('Dime la trama de Cuaderno lunar',
            [BOOK, {**PAGE, 'conflicts_with': ['otra fuente']}], intent='summary'))

    def test_manga_identity_does_not_use_anime_adaptation(self):
        from .ai_narrative_answers import request_for, bound_sources
        req = request_for('Dime la trama del manga Sendero azul')
        page = {**PAGE, 'title': 'Sendero azul',
                'identity_text': 'Sendero azul es una serie de anime de Ana Robles.'}
        self.assertEqual(bound_sources(req, [page]), [])

    def test_single_word_manga_uses_documented_identity(self):
        from .ai_quick_answers import reference_answer
        page = {**PAGE, 'title': 'Horizonte',
                'identity_text': 'Horizonte es un manga de Ana Robles.'}
        result = reference_answer('¿Cuál es la trama de Horizonte?', [page], intent='summary')
        self.assertIsNotNone(result)
        self.assertIn('Ana viaja', result.text)

    def test_missing_evidence_is_not_a_list_of_links(self):
        from .ai_quick_answers import reference_answer
        self.assertIsNone(reference_answer('Dime la trama de Cuaderno lunar', [], intent='summary'))
