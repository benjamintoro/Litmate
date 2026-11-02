from django.test import SimpleTestCase

from .ai_narrative_answers import _content, narrative_answer


class SynopsisPipelineTests(SimpleTestCase):
    def test_content_preserves_description(self):
        source = {'kind': 'web', 'source': 'Wikipedia', 'title': 'La ciudad de cristal azul',
                  'author': 'Fuente web', 'description': 'La novela sigue a una investigadora que descubre una ciudad oculta bajo el mar y debe decidir si revela su existencia.',
                  'license': 'CC-BY-SA-4.0'}
        self.assertIn('investigadora', _content(source))