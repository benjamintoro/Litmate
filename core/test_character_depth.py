"""Extraction regression: declared character sections, not arbitrary mentions."""
from django.test import SimpleTestCase
from .literary_web import character_content


class CharacterDepthTests(SimpleTestCase):
    def test_relevant_characters_is_an_explicit_section_not_a_role_classification(self):
        html = '<h2>Personajes relevantes</h2><p><b>Elena</b>: Es la viajera que busca un mapa.</p>'
        result = character_content(html, title='Las rutas', context='Elena')
        self.assertEqual(result['character_facts'][0]['name'], 'Elena')
        self.assertFalse(result['character_facts'][0].get('classification'))

    def test_published_paragraph_definitions_are_not_ignored(self):
        html = '<h2>Personajes</h2><p><b>Elena</b>: Es la viajera que busca un mapa.</p>'
        result = character_content(html, title='Las rutas', context='Las rutas personajes Elena')
        self.assertEqual([fact['name'] for fact in result['character_facts']], ['Elena'])
        self.assertIn('Es la viajera que busca un mapa.', result['passage'])

    def test_linked_paragraph_in_character_section_has_a_literal_subject(self):
        html = '<h2>Personajes</h2><p><a href="/wiki/Clara">Clara</a> es amiga de Elena durante el viaje.</p>'
        result = character_content(html, title='Las rutas', context='Clara')
        self.assertEqual([fact['name'] for fact in result['character_facts']], ['Clara'])

    def test_requested_character_is_selected_before_bounded_output(self):
        html = '<h2>Personajes</h2><ul>' + ''.join(
            '<li><b>Viajero ' + str(i) + '</b>: Es un viajero que busca un mapa.</li>' for i in range(20)) + '</ul>'
        result = character_content(html, title='Las rutas', context='Las rutas\nDime los personajes Viajero 19')
        self.assertIn('Viajero 19', [fact['name'] for fact in result['character_facts']])
        self.assertLessEqual(len(result['character_facts']), 12)
        self.assertLessEqual(len(result['passage']), 1800)

    def test_arbitrary_bold_mentions_outside_characters_are_not_facts(self):
        html = '<h2>Opiniones</h2><p><b>Elena</b>: Es la viajera que busca un mapa.</p>'
        self.assertEqual(character_content(html, title='Las rutas')['character_facts'], [])
