"""Una coincidencia léxica no sustituye la obra de una continuación."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .literary_ai import ChatResult


NOVEL = {'kind': 'web', 'source': 'Wikipedia', 'title': 'El Señor de los Anillos',
    'author': 'Fuente web', 'url': 'https://es.wikipedia.org/wiki/El_Se%C3%B1or_de_los_Anillos',
    'identity_text': 'El Señor de los Anillos es una novela de J. R. R. Tolkien.',
    'description': 'El Señor de los Anillos es una novela de J. R. R. Tolkien. '
                   'Frodo debe destruir el Anillo Único.',
    'read_mode': 'extracto de introducción'}
MATH = {'kind': 'web', 'source': 'Wikipedia', 'title': 'Anillo (matemática)',
    'author': 'Fuente web', 'url': 'https://es.wikipedia.org/wiki/Anillo_(matem%C3%A1tica)',
    'description': 'En álgebra abstracta, un anillo es un sistema algebraico formado '
                   'por un conjunto y dos operaciones internas.',
    'read_mode': 'extracto de introducción'}
HISTORY = [{'accepted': True, 'question': '¿Quién es Frodo?',
            'answer': 'Frodo debe destruir el Anillo Único.', 'books': [], 'sources': [NOVEL]}]
QUESTION = '¿Qué relación tiene ese antagonista con el Anillo?'


class ContextReferenceScopeTests(SimpleTestCase):
    @override_settings(LITMATE_AI_USE_WEB=True, LITMATE_AI_CATALOG_FALLBACK=False)
    def test_http_worker_backup_does_not_replace_the_active_novel_by_algebra(self):
        from .literary_ai_views import _model_answer
        assistant = SimpleNamespace(reply=lambda *args, **kwargs: ChatResult('Sin respuesta comprobada.', 'unavailable'))
        client = SimpleNamespace(calls=1, usage={}, provider='simulated')
        with patch('core.literary_ai_views.build_assistant', return_value=(assistant, client)), \
                patch('core.literary_search.retrieve_web', return_value=[MATH]):
            result, _ = _model_answer(QUESTION, HISTORY, {}, QUESTION)
        self.assertEqual(result.status, 'unavailable')
        self.assertNotIn('álgebra', result.text)

    def test_reference_api_cannot_publish_an_unbound_page_for_a_followup(self):
        from .ai_quick_answers import reference_answer
        result = reference_answer(QUESTION, [MATH], history=HISTORY, intent='analysis')
        self.assertIsNone(result)

    def test_an_already_identified_novel_page_can_still_be_a_partial_reference(self):
        from .ai_quick_answers import reference_answer
        result = reference_answer('¿Y qué pasa con ese Anillo?', [NOVEL], history=HISTORY, intent='analysis')
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'answered')
        self.assertEqual(result.sources[0]['url'], NOVEL['url'])
        self.assertIn('Frodo', result.text)

    def test_explicit_work_cannot_be_replaced_by_a_character_from_another_saga(self):
        from .ai_quick_answers import reference_answer
        other = {**NOVEL, 'title': 'Albus Dumbledore',
                 'url': 'https://es.wikipedia.org/wiki/Albus_Dumbledore',
                 'identity_text': 'Albus Dumbledore es un personaje de Harry Potter, de J. K. Rowling.',
                 'description': 'Albus Dumbledore es un personaje de la saga Harry Potter.'}
        for question in ('¿Qué personaje de El Señor de los Anillos se llama Severus Snape?',
                         '?Qué personaje de El Señor de los Anillos se llama Severus Snape?'):
            with self.subTest(question=question):
                self.assertIsNone(reference_answer(question, [other]))

    def test_new_explicit_literary_topic_does_not_inherit_the_old_work_filter(self):
        from .ai_quick_answers import reference_answer
        source = {**NOVEL, 'title': 'Bibliotecas y lectura',
                  'url': 'https://example.org/bibliotecas',
                  'description': 'Las bibliotecas públicas conservan libros y facilitan la lectura.'}
        result = reference_answer('Recomiéndame libros sobre bibliotecas', [source], history=HISTORY)
        self.assertIsNotNone(result)

    def test_literal_neighbour_and_companion_role_answers_the_requested_relationship(self):
        from .ai_character_answers import answer_from_sources, request_for
        book = {'kind': 'book', 'title': 'El valle de prueba', 'author': 'Una Autora',
                'source': 'Conocimiento literario local', 'url': 'https://example.org/valle'}
        role = 'Labrador vecino de Rafael que lo acompaña como escudero.'
        page = {'kind': 'web', 'title': book['title'], 'author': 'Fuente web',
                'source': 'Conocimiento literario local', 'url': book['url'], 'license': 'CC0-1.0',
                'work_title': book['title'], 'work_author': book['author'], 'work_binding_verified': True,
                'description': 'Bruno: ' + role,
                'character_facts': [{'name': 'Bruno', 'role': role}]}
        question = '¿Qué relación tienen Bruno y Rafael?'
        history = [{'accepted': True, 'question': '¿Quién es Bruno?', 'answer': 'Bruno: ' + role,
                    'books': [book], 'sources': [book, page]}]
        result = answer_from_sources(question, request_for(question, history), [book, page])
        self.assertIsNotNone(result)
        self.assertIn(role, result.text)
