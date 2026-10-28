from django.test import SimpleTestCase

from .ai_character_answers import request_for, answer_from_sources


class ProtagonistFromDescriptionTests(SimpleTestCase):
    def test_explicit_protagonist_role_in_description_is_used(self):
        book = {'kind': 'book', 'title': 'La ciudad de cristal azul', 'author': 'Elena Vargas',
                'source': 'Conocimiento literario local', 'url': 'https://example.org/ciudad'}
        page = {'kind': 'web', 'title': book['title'], 'author': 'Fuente web',
                'source': 'Wikipedia', 'url': book['url'], 'license': 'CC-BY-SA-4.0',
                'description': 'Mara Solís: Es la protagonista que descubre la ciudad oculta.',
                'character_facts': []}
        request = request_for('¿Quién es el protagonista?', __import__('core.test_character_context_resolution', fromlist=['history']).history.__wrapped__ if hasattr(__import__('core.test_character_context_resolution', fromlist=['history']).history, '__wrapped__') else None) if False else None
        # Build request manually via request_for with history containing book
        from copy import deepcopy
        hist = [{'accepted': True, 'question': 'Habla de La ciudad de cristal azul',
                 'answer': 'Es una novela.', 'books': [deepcopy(book)], 'sources': [deepcopy(book), deepcopy(page)]}]
        request = request_for('¿Quién es el protagonista?', hist)
        self.assertIsNotNone(request)
        result = answer_from_sources('¿Quién es el protagonista?', request, [deepcopy(book), deepcopy(page)])
        self.assertIsNotNone(result)
        self.assertIn('Mara Solís', result.text)

    def test_no_protagonist_without_explicit_evidence(self):
        book = {'kind': 'book', 'title': 'La ciudad de cristal azul', 'author': 'Elena Vargas',
                'source': 'Conocimiento literario local', 'url': 'https://example.org/ciudad'}
        page = {'kind': 'web', 'title': book['title'], 'author': 'Fuente web',
                'source': 'Wikipedia', 'url': book['url'], 'license': 'CC-BY-SA-4.0',
                'description': 'Una ciudad oculta bajo el mar.', 'character_facts': []}
        from copy import deepcopy
        hist = [{'accepted': True, 'question': 'Habla de La ciudad de cristal azul',
                 'answer': 'Es una novela.', 'books': [deepcopy(book)], 'sources': [deepcopy(book), deepcopy(page)]}]
        request = request_for('¿Quién es el protagonista?', hist)
        # May be None or result None
        if request is not None:
            result = answer_from_sources('¿Quién es el protagonista?', request, [deepcopy(book), deepcopy(page)])
            self.assertTrue(result is None or result.status != 'answered')