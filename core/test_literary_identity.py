"""Identidad y continuidad sin red ni conocimiento inventado por el modelo."""
from django.test import SimpleTestCase
from unittest.mock import Mock

from .literary_identity import (bind_source, book_named_in_message, confirmed_aliases,
                                resolve_followup_context, same_work, title_matches,
                                work_identity)
from .literary_quality import resolve_followup_books


BOOK = {'kind': 'book', 'source': 'Conocimiento literario local',
        'title': 'Diario secreto de Papelucho y el marciano', 'author': 'Marcela Paz',
        'url': 'https://ci.nii.ac.jp/ncid/BA64258717',
        'description': 'Papelucho comparte sus aventuras con Det, su amigo marciano.',
        'confirmed_aliases': [{'title': 'Papelucho y el marciano',
            'source_url': 'https://ci.nii.ac.jp/ncid/BA64258717',
            'evidence': 'Diario secreto de Papelucho y el marciano. Otro título: Papelucho y el marciano.'}]}
PUBLIC = {'kind': 'web', 'source': 'Editorial SM', 'title': BOOK['title'],
          'author': 'Fuente web', 'url': 'https://literaturasm.cl/diario-secreto-de-papelucho-y-el-marciano/',
          'identity_text': 'Diario secreto de Papelucho y el marciano es un libro de Marcela Paz.',
          'description': 'Papelucho: Niño protagonista. Det: Amigo marciano de Papelucho.',
          'character_facts': [{'name': 'Papelucho', 'role': 'Niño protagonista'},
                              {'name': 'Det', 'role': 'Amigo marciano de Papelucho'}]}


class LiteraryIdentityTests(SimpleTestCase):
    def test_web_title_suffix_binds_only_with_author_identity(self):
        page = {**PUBLIC, 'title': BOOK['title'] + ' - Wikipedia, la enciclopedia libre',
                'identity_text': f'{BOOK["title"]} es un libro de {BOOK["author"]}.'}
        self.assertTrue(bind_source(page, BOOK).get('work_binding_verified'))
        without_author = {**page, 'identity_text': 'Una página sobre esta obra.'}
        self.assertFalse(bind_source(without_author, BOOK).get('work_binding_verified'))
        different_volume = {**page, 'title': BOOK['title'] + ': el regreso del marciano'}
        self.assertFalse(bind_source(different_volume, BOOK).get('work_binding_verified'))

    def test_book_named_in_message_accepts_confirmed_alias(self):
        self.assertTrue(book_named_in_message(
            BOOK, '¿De qué trata Diario secreto de Papelucho y el marciano?'))
        self.assertTrue(book_named_in_message(BOOK, '¿De qué trata Papelucho y el marciano?'))
        self.assertFalse(book_named_in_message(BOOK, '¿De qué trata otra obra?'))

    def test_alias_requires_bibliographic_provenance(self):
        self.assertTrue(title_matches('Papelucho y el marciano', BOOK))
        for change in ({'confirmed_aliases': ['Papelucho y el marciano']},
                       {'confirmed_aliases': [{**BOOK['confirmed_aliases'][0], 'source_url': 'https://evil.example/'}]},
                       {'confirmed_aliases': [{**BOOK['confirmed_aliases'][0], 'evidence': 'Otro libro sin relación'}]}):
            with self.subTest(change=change):
                self.assertFalse(title_matches('Papelucho y el marciano', {**BOOK, **change}))

    def test_author_and_specific_volume_must_agree(self):
        short = {**BOOK, 'title': 'Papelucho y el marciano', 'confirmed_aliases': []}
        self.assertTrue(same_work(short, BOOK))
        self.assertFalse(same_work({**short, 'author': 'Otra autora'}, BOOK))
        self.assertFalse(same_work({**BOOK, 'title': 'Papelucho perdido', 'confirmed_aliases': []}, BOOK))

    def test_public_page_requires_author_and_rejects_adaptation(self):
        self.assertTrue(same_work(PUBLIC, BOOK))
        for text in ('Un libro de otra autora.', 'Una película basada en el libro de Marcela Paz.'):
            self.assertFalse(same_work({**PUBLIC, 'identity_text': text}, BOOK))

    def test_binding_preserves_web_provenance(self):
        bound = bind_source(PUBLIC, BOOK)
        self.assertTrue(bound['work_binding_verified'])
        self.assertEqual(bound['author'], 'Fuente web')
        self.assertEqual(bound['work_author'], 'Marcela Paz')
        self.assertEqual(work_identity(bound)['title'], BOOK['title'])
        self.assertFalse(work_identity({'work_binding_verified': True}))

    def test_invalid_isbn_cannot_join_two_different_books(self):
        bad = {**BOOK, 'isbns': ['1234567890123']}
        self.assertFalse(same_work({**bad, 'title': 'Otra novela', 'confirmed_aliases': []}, bad))

    def test_bibliographic_identity_roundtrip_preserves_proven_aliases_and_ids(self):
        original = {**BOOK, 'isbns': ['9789563495768'], 'work_id': 'litmate:verified-original'}
        identity = work_identity(original)
        for _ in range(3):
            identity = work_identity(identity)
        self.assertEqual(identity['work_id'], original['work_id'])
        self.assertEqual(identity['isbns'], ['9789563495768'])
        self.assertEqual(identity['source'], 'Conocimiento literario local')
        self.assertEqual(identity['url'], BOOK['url'])
        self.assertTrue(title_matches('Papelucho y el marciano', identity))
        short_page = {**PUBLIC, 'title': 'Papelucho y el marciano'}
        self.assertTrue(same_work(short_page, identity))
        self.assertTrue(bind_source(short_page, identity)['work_binding_verified'])

    def test_unknown_origin_cannot_gain_alias_provenance_through_roundtrips(self):
        original = {**BOOK, 'source': 'Marca inventada', 'url': 'https://evil.example/',
                    'work_id': 'invented:claim'}
        identity = work_identity(original)
        for _ in range(3):
            identity = work_identity(identity)
        self.assertEqual(identity['confirmed_aliases'], [])
        self.assertNotIn('source', identity)
        self.assertNotIn('url', identity)
        self.assertNotEqual(identity['work_id'], 'invented:claim')
        self.assertFalse(title_matches('Papelucho y el marciano', identity))

    def test_bibliographic_label_does_not_preserve_unrelated_private_or_fake_urls(self):
        for url in ('http://127.0.0.1/private', 'https://10.0.0.1/',
                    'https://8.8.8.8/',
                    'https://ci.nii.ac.jp.evil.example/', 'https://user:pass@ci.nii.ac.jp/',
                    'https://ci.nii.ac.jp:8443/'):
            identity = work_identity({**BOOK, 'url': url})
            self.assertNotIn('url', identity)
            self.assertEqual(identity['source'], 'Conocimiento literario local')


class LiteraryFollowupTests(SimpleTestCase):
    def history(self, books=None):
        return [{'accepted': True, 'question': BOOK['title'], 'answer': 'La obra de Marcela Paz.',
                 'books': books or [BOOK], 'sources': [BOOK, PUBLIC]}]

    def test_possessive_and_named_entity_preserve_work(self):
        for message in ('¿Y sus personajes cuáles son?', '¿Qué sucede con Det?', '¿Quién es Det?'):
            context = resolve_followup_context(message, self.history())
            self.assertEqual(context['books'], [BOOK])
            self.assertFalse(context['ambiguous'])
        self.assertEqual(resolve_followup_context('¿Qué sucede con Det?', self.history())['entities'], ['Det'])

    def test_two_books_without_entity_need_clarification(self):
        other = {**BOOK, 'title': 'Otro libro', 'author': 'Otra autora', 'confirmed_aliases': []}
        self.assertTrue(resolve_followup_context('¿Y sus personajes?', self.history([BOOK, other]))['ambiguous'])
        self.assertEqual(resolve_followup_books('¿Y el segundo?', self.history([BOOK, other])), [other])

    def test_rejected_turn_and_new_unknown_title_do_not_inherit(self):
        rejected = [{**self.history()[0], 'accepted': False}]
        self.assertEqual(resolve_followup_books('¿Y sus personajes?', rejected), [])
        for message in ('Ahora sobre otro libro', '¿Y qué sucede en Crimen y castigo?',
                        'Dime los personajes de «El principito»'):
            self.assertEqual(resolve_followup_books(message, self.history()), [])

    def test_unknown_recollection_does_not_inherit_a_previous_books_possessive(self):
        for message in ('Recuerdo una escena de un libro, pero no su título',
                        'Recuerdo una escena, pero no su título',
                        'Busco un libro cuyo protagonista pierde su memoria'):
            with self.subTest(message=message):
                self.assertEqual(resolve_followup_books(message, self.history()), [])
        self.assertEqual(resolve_followup_books('Recuerdo una escena de ese libro y su protagonista',
                                               self.history()), [BOOK])

    def test_explicit_known_title_switches_to_earlier_work(self):
        other = {'title': 'Dune', 'author': 'Frank Herbert', 'kind': 'book'}
        history = self.history() + [{'accepted': True, 'books': [other]}]
        self.assertEqual(resolve_followup_books('¿Y los personajes de Papelucho y el marciano?', history), [BOOK])
        self.assertEqual(resolve_followup_context('Compara Dune con Papelucho y el marciano', history)['books'], [])
        self.assertTrue(resolve_followup_context('Compara Dune con Papelucho y el marciano', history)['ambiguous'])

    def test_series_title_prefix_does_not_inherit_the_first_volume(self):
        first_volume = {'kind': 'book', 'title': 'Papelucho', 'author': 'Marcela Paz'}
        history = self.history([first_volume])
        for message in ('Dime los personajes de Papelucho y el marciano',
                        'Háblame de Papelucho perdido',
                        '¿Y los personajes de Papelucho en la clínica?',
                        'Cuéntame sobre «Papelucho y su hermana Ji»'):
            with self.subTest(message=message):
                self.assertEqual(resolve_followup_context(message, history)['books'], [])

    def test_question_continuations_after_short_title_preserve_the_work(self):
        first_volume = {'kind': 'book', 'title': 'Papelucho', 'author': 'Marcela Paz'}
        history = self.history([first_volume])
        for message in ('Háblame de Papelucho y sus personajes',
                        'Dime los personajes de Papelucho',
                        'Háblame de Papelucho y explica su argumento',
                        'Háblame de Papelucho de Marcela Paz'):
            with self.subTest(message=message):
                self.assertEqual(resolve_followup_context(message, history)['books'], [first_volume])

    def test_specific_volume_and_explicit_comparison_keep_distinct_identities(self):
        first_volume = {'kind': 'book', 'title': 'Papelucho', 'author': 'Marcela Paz'}
        history = self.history([first_volume, BOOK])
        self.assertEqual(resolve_followup_context(
            'Dime los personajes de Papelucho y el marciano', history)['books'], [BOOK])
        for message in ('Compara Papelucho con Papelucho y el marciano',
                        'Compara Papelucho y Papelucho y el marciano'):
            with self.subTest(message=message):
                self.assertTrue(resolve_followup_context(message, history)['ambiguous'])

    def test_sanitized_history_keeps_alias_evidence_for_followup_and_search(self):
        from .literary_ai import sanitized_history
        from .literary_research import public_research_queries
        cleaned = sanitized_history(sanitized_history(self.history()))
        books = resolve_followup_books('Dime los personajes de Papelucho y el marciano', cleaned)
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]['author'], 'Marcela Paz')
        queries = public_research_queries('¿Qué sucede con Det?', books)
        self.assertEqual(len(queries), 2)
        self.assertIn('"Papelucho y el marciano"', queries[1])


class LiteraryFastDetailsIntegrationTests(SimpleTestCase):
    def test_conflicting_verified_character_facts_return_to_the_audited_conversation(self):
        from .ai_public_details import character_answer
        pages = []
        for identity in ('extraterrestre', 'humano'):
            statement = 'Det es ' + identity + '.'
            pages.append({**PUBLIC, 'description': PUBLIC['description'] + ' ' + statement,
                'literary_facts': [{'topic': 'characters', 'subject': 'Det',
                                   'relation': 'identity', 'value': identity,
                                   'evidence': statement}]})
        result = character_answer('Dime los personajes de Papelucho y el marciano', [],
                                  Mock(return_value=[BOOK]), Mock(return_value=pages))
        self.assertIsNone(result)

    def test_confirmed_alias_produces_facts_without_matching_another_volume(self):
        from .ai_public_details import character_answer
        book_search, public_search = Mock(return_value=[BOOK]), Mock(return_value=[PUBLIC])
        result = character_answer('Dime los personajes de Papelucho y el marciano', [], book_search, public_search)
        self.assertIsNotNone(result)
        self.assertIn('**Det**', result.text)
        self.assertEqual(result.books[0]['title'], BOOK['title'])

    def test_followup_reuses_received_character_evidence_without_network(self):
        from .ai_public_details import character_answer
        history = [{'accepted': True, 'books': [BOOK], 'sources': [BOOK, PUBLIC]}]
        book_search, public_search = Mock(), Mock()
        result = character_answer('¿Y sus personajes cuáles son?', history, book_search, public_search)
        self.assertIsNotNone(result)
        self.assertIn('**Det**', result.text)
        book_search.assert_not_called()
        public_search.assert_not_called()
