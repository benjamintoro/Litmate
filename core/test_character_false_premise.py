"""Una pertenencia falsa se corrige con dos páginas literales, no con un error."""
from unittest.mock import patch

from django.test import SimpleTestCase

from .ai_character_answers import premise_answer, request_for


def wiki(title, identity, description=''):
    from urllib.parse import quote
    url = 'https://es.wikipedia.org/wiki/' + quote(title.replace(' ', '_'))
    return {'kind': 'web', 'source': 'Wikipedia', 'title': title,
            'author': 'Fuente web', 'url': url,
            'description': description or identity, 'identity_text': identity,
            'license': 'CC-BY-SA-4.0', 'read_mode': 'extracto de introducción',
            'attribution': {'authors': 'Wikipedia contributors', 'title': title,
                            'url': url, 'revision_id': '12345',
                            'license_url': 'https://creativecommons.org/licenses/by-sa/4.0/'}}


SNAPE = wiki(
    'Severus Snape',
    'Severus Snape es un personaje ficticio de la serie de novelas Harry Potter '
    'de J. K. Rowling. En las cinco primeras novelas es profesor de Pociones.')
LOTR = wiki(
    'El Señor de los Anillos',
    'El Señor de los Anillos es una novela de fantasía épica escrita por '
    'J. R. R. Tolkien. Su historia se desarrolla en la Tierra Media.',
    'Personajes (descripciones del artículo): Frodo Bolsón: protagonista de la novela. '
    'Samsagaz Gami: jardinero y amigo de Frodo.')


class FalsePremiseTests(SimpleTestCase):
    def test_request_recognizes_a_character_attribution_to_a_work(self):
        request = request_for('¿Qué personaje de El Señor de los Anillos se llama Severus Snape?')
        self.assertEqual(request['task'], 'premise')
        self.assertEqual(request['title'], 'el senor de los anillos')
        self.assertEqual(request['names'], ['severus snape'])
        self.assertFalse(request['ambiguous'])

    @patch('core.literary_search.search_wikipedia')
    def test_a_character_from_another_work_is_corrected_with_both_citations(self, search):
        search.side_effect = lambda query: [SNAPE] if 'snape' in query.casefold() else [LOTR]
        question = '¿Qué personaje de El Señor de los Anillos se llama Severus Snape?'
        result = premise_answer(question, request_for(question))
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'answered')
        self.assertIn('Harry Potter', result.text)
        self.assertIn('no consta', result.text)
        self.assertNotIn('servicio de IA', result.text)
        self.assertEqual(len(result.sources), 2)
        self.assertEqual(len({source['id'] for source in result.sources}), 2)
        self.assertEqual(result.diagnostics['false_premise_correction'], True)

    @patch('core.literary_search.search_wikipedia')
    def test_a_true_attribution_is_not_corrected(self, search):
        frodo = wiki(
            'Frodo Bolsón',
            'Frodo Bolsón es un personaje ficticio de la novela El Señor de los '
            'Anillos de J. R. R. Tolkien.')
        search.side_effect = lambda query: [frodo] if 'frodo' in query.casefold() else [LOTR]
        question = '¿Qué personaje de El Señor de los Anillos se llama Frodo Bolsón?'
        self.assertIsNone(premise_answer(question, request_for(question)))

    @patch('core.literary_search.search_wikipedia')
    def test_a_name_present_in_the_work_page_is_not_declared_absent(self, search):
        work = wiki(
            'El Señor de los Anillos',
            LOTR['identity_text'],
            'Personajes: Severus Snape aparece en una adaptación discutida.')
        search.side_effect = lambda query: [SNAPE] if 'snape' in query.casefold() else [work]
        question = '¿Qué personaje de El Señor de los Anillos se llama Severus Snape?'
        self.assertIsNone(premise_answer(question, request_for(question)))

    @patch('core.literary_search.search_wikipedia')
    def test_a_real_person_profile_is_not_used_for_a_fictional_correction(self, search):
        person = wiki(
            'Severus Snape',
            'Severus Snape fue un profesor británico de química.')
        search.side_effect = lambda query: [person] if 'snape' in query.casefold() else [LOTR]
        question = '¿Qué personaje de El Señor de los Anillos se llama Severus Snape?'
        self.assertIsNone(premise_answer(question, request_for(question)))


class ObjectRelationTests(SimpleTestCase):
    def setUp(self):
        from urllib.parse import quote
        title = 'El Señor de los Anillos'
        url = 'https://es.wikipedia.org/wiki/' + quote(title.replace(' ', '_'))
        self.source = {
            'id': 1, 'kind': 'web', 'source': 'Wikipedia', 'title': title,
            'author': 'Fuente web', 'url': url, 'license': 'CC-BY-SA-4.0',
            'read_mode': 'pasaje de sección de artículo público',
            'identity_text': title + ' es una novela de J. R. R. Tolkien.',
            'description': 'Frodo Bolsón: protagonista de la novela. '
                           'Samsagaz Gami: jardinero y amigo de Frodo.',
            'character_facts': [{'name': 'Sauron', 'role': 'señor oscuro',
                                 'classification': 'antagonist'}],
            'narrative_context': (
                'La novela narra el viaje del protagonista principal, Frodo Bolsón, '
                'hobbit de la Comarca, para destruir el Anillo Único y la consiguiente '
                'guerra que provocará el enemigo para recuperarlo, ya que es la principal '
                'fuente de poder de su creador, el señor oscuro Sauron.'),
        }
        self.history = [{'accepted': True, 'question': '¿Quién es el antagonista?',
                         'answer': '**Sauron**: Es el señor oscuro de la obra.',
                         'books': [], 'sources': [self.source]}]

    def test_role_object_request_resolves_the_antagonist_and_the_object(self):
        request = request_for('¿Qué relación tiene ese antagonista con el Anillo?',
                              self.history)
        self.assertEqual(request['task'], 'object_relation')
        self.assertEqual(request['names'], ['Sauron'])
        self.assertEqual(request['object_name'], 'el anillo')
        self.assertFalse(request['ambiguous'])

    def test_explicit_creator_and_power_passage_answers_the_relation(self):
        from .ai_character_answers import object_relation_answer
        request = request_for('¿Qué relación tiene ese antagonista con el Anillo?',
                              self.history)
        result = object_relation_answer('¿Qué relación tiene ese antagonista con el Anillo?',
                                        request, [self.source])
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'answered')
        self.assertIn('creador', result.text)
        self.assertIn('Sauron', result.text)
        self.assertEqual(result.diagnostics['character_task'], 'object_relation')

    def test_mere_coexistence_does_not_invent_a_relation(self):
        from .ai_character_answers import object_relation_answer
        source = dict(self.source)
        source['narrative_context'] = ('Frodo destruyó el Anillo Único mientras Sauron '
                                       'observaba desde la torre.')
        request = request_for('¿Qué relación tiene ese antagonista con el Anillo?',
                              self.history)
        self.assertIsNone(object_relation_answer(
            '¿Qué relación tiene ese antagonista con el Anillo?', request, [source]))
