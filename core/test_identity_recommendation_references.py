"""Referencias a nuevas recomendaciones sin sustituir ni inventar la obra base."""
from django.test import SimpleTestCase

from .literary_identity import resolve_followup_context


DUNE = {'kind': 'book', 'title': 'Dune', 'author': 'Frank Herbert',
        'source': 'Catálogo LitMate', 'book_id': 'controlled-dune'}
MESSIAH = {'kind': 'book', 'title': 'El mesías de Dune', 'author': 'Frank Herbert',
           'source': 'Catálogo LitMate', 'book_id': 'controlled-messiah'}
PAPELUCHO = {'kind': 'book', 'title': 'Papelucho y el marciano', 'author': 'Marcela Paz',
            'source': 'Catálogo LitMate', 'book_id': 'controlled-papelucho'}


def history(*lists):
    return [{'accepted': True, 'books': books, 'sources': []} for books in lists]


def web_work(title, author):
    from urllib.parse import quote
    url = 'https://es.wikipedia.org/wiki/' + quote(title.replace(' ', '_'))
    identity = title + ' es una novela escrita por ' + author + '.'
    return {'kind': 'web', 'title': title, 'author': 'Fuente web', 'source': 'Wikipedia',
            'url': url, 'description': identity, 'identity_text': identity,
            'license': 'CC-BY-SA-4.0', 'read_mode': 'extracto de introducción',
            'attribution': {'authors': 'Wikipedia contributors', 'title': title, 'url': url,
                            'revision_id': '12345',
                            'license_url': 'https://creativecommons.org/licenses/by-sa/4.0/'}}


def web_history(*works):
    return [{'accepted': True, 'books': [], 'sources': [work]} for work in works]


class RecommendationReferenceTests(SimpleTestCase):
    def test_other_book_from_same_author_keeps_only_accepted_active_identity(self):
        for message in ('Otro del mismo autor', 'Recomiéndame libros de ese autor',
                        'Busco un libro del mismo autor', 'Más de su autor'):
            with self.subTest(message=message):
                result = resolve_followup_context(message, history([DUNE]))
                self.assertEqual(result['books'], [DUNE])
                self.assertEqual(result['reason'], 'same_author')
                self.assertFalse(result['ambiguous'])

    def test_similar_book_keeps_only_accepted_active_identity(self):
        for message in ('Otro parecido', 'Recomiéndame uno similar',
                        'Libros parecidos a ese libro', 'Algo parecido al anterior'):
            with self.subTest(message=message):
                result = resolve_followup_context(message, history([DUNE]))
                self.assertEqual(result['books'], [DUNE])
                self.assertEqual(result['reason'], 'similar')
                self.assertFalse(result['ambiguous'])

    def test_ordinal_selects_base_but_preserves_requested_relation(self):
        for message, reason in (('Otro del mismo autor del segundo', 'same_author'),
                                ('Otro parecido al segundo', 'similar')):
            with self.subTest(message=message):
                result = resolve_followup_context(message, history([DUNE, PAPELUCHO]))
                self.assertEqual(result['books'], [PAPELUCHO])
                self.assertEqual(result['reason'], reason)

    def test_explicit_known_title_can_select_older_topic(self):
        result = resolve_followup_context('Otro del mismo autor de Dune',
                                          history([DUNE], [PAPELUCHO]))
        self.assertEqual(result['books'], [DUNE])
        self.assertEqual(result['reason'], 'same_author')
        result = resolve_followup_context('Otro parecido a Dune',
                                          history([DUNE], [PAPELUCHO]))
        self.assertEqual(result['books'], [DUNE])
        self.assertEqual(result['reason'], 'similar')

    def test_relation_language_before_known_title_is_not_treated_as_a_new_title(self):
        for message in ('Otro del mismo autor de Dune', 'Otro parecido a Dune'):
            with self.subTest(message=message):
                result = resolve_followup_context(message, history([DUNE], [PAPELUCHO]))
                self.assertEqual(result['books'], [DUNE])

    def test_multiple_authors_require_selection_instead_of_picking_arbitrarily(self):
        for message, reason in (('Otro del mismo autor', 'same_author'),
                                ('Otro parecido', 'similar')):
            with self.subTest(message=message):
                result = resolve_followup_context(message, history([DUNE, PAPELUCHO]))
                self.assertEqual(result['books'], [])
                self.assertTrue(result['ambiguous'])
                self.assertEqual(result['reason'], reason)

    def test_same_author_list_can_preserve_all_known_books_for_deduplication(self):
        result = resolve_followup_context('Otro del mismo autor', history([DUNE, MESSIAH]))
        self.assertEqual(result['books'], [DUNE, MESSIAH])
        self.assertEqual(result['reason'], 'same_author')
        self.assertFalse(result['ambiguous'])

    def test_similar_to_two_books_is_ambiguous_even_if_author_is_shared(self):
        result = resolve_followup_context('Otro parecido', history([DUNE, MESSIAH]))
        self.assertEqual(result['books'], [])
        self.assertTrue(result['ambiguous'])

    def test_unknown_explicit_title_does_not_inherit_an_unrelated_work(self):
        for message in ('Otro parecido a Dune', 'Otro del mismo autor de Dune',
                        'Otro parecido a "Dune"', 'Otro del mismo autor de «Dune»'):
            with self.subTest(message=message):
                result = resolve_followup_context(message, history([PAPELUCHO]))
                self.assertEqual(result['books'], [])

    def test_rejected_turn_never_sets_the_base_work(self):
        previous = history([DUNE]) + [{'accepted': False, 'books': [PAPELUCHO]}]
        self.assertEqual(resolve_followup_context('Otro parecido', previous)['books'], [DUNE])

    def test_no_history_does_not_invent_a_reference(self):
        for message in ('Otro parecido', 'Otro del mismo autor'):
            with self.subTest(message=message):
                self.assertEqual(resolve_followup_context(message, [])['books'], [])

    def test_an_independent_new_recollection_does_not_inherit_previous_identity(self):
        result = resolve_followup_context('Recuerdo otro libro parecido a ese, pero no su título',
                                          history([DUNE]))
        self.assertEqual(result['books'], [])

    def test_new_generic_topic_is_not_a_relation_to_the_previous_book(self):
        for message in ('Recomiéndame otro libro de historia de Corea',
                        'Cambiemos: quiero otro parecido sobre arte japonés'):
            with self.subTest(message=message):
                self.assertEqual(resolve_followup_context(message, history([DUNE]))['books'], [])

    def test_factual_same_author_question_is_not_a_new_recommendation(self):
        for message in ('¿Es del mismo autor?', '¿El segundo es del mismo autor?',
                        '¿Cuáles son del mismo autor?'):
            with self.subTest(message=message):
                result = resolve_followup_context(message, history([DUNE, PAPELUCHO]))
                self.assertNotEqual(result['reason'], 'same_author')

    def test_regular_ordinal_keeps_existing_contract(self):
        result = resolve_followup_context('Háblame del segundo', history([DUNE, PAPELUCHO]))
        self.assertEqual(result['books'], [PAPELUCHO])
        self.assertEqual(result['reason'], 'ordinal')

    def test_web_only_history_restores_the_order_of_works_for_ordinals(self):
        lotr = web_work('El Señor de los Anillos', 'J. R. R. Tolkien')
        harry = web_work('Harry Potter y la piedra filosofal', 'J. K. Rowling')
        turns = web_history(lotr, harry)
        result = resolve_followup_context(
            'Volvamos al primer libro. ¿Quién debía destruir el Anillo?', turns)
        self.assertEqual([book['title'] for book in result['books']],
                         ['El Señor de los Anillos'])
        self.assertEqual(result['reason'], 'ordinal')
        self.assertFalse(result['ambiguous'])
        result = resolve_followup_context('Háblame del segundo', turns)
        self.assertEqual([book['title'] for book in result['books']],
                         ['Harry Potter y la piedra filosofal'])

    def test_a_character_profile_is_not_mistaken_for_the_history_work(self):
        snape = web_work('Severus Snape', 'J. K. Rowling')
        snape['identity_text'] = ('Severus Snape es un personaje ficticio de la serie de novelas '
                                  'Harry Potter de J. K. Rowling.')
        snape['description'] = snape['identity_text']
        result = resolve_followup_context('Háblame del primero', web_history(snape))
        self.assertEqual(result['books'], [])
