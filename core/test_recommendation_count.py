"""La petición de una obra limita la generación; no se relaja su validación."""
from unittest.mock import patch

from django.test import SimpleTestCase

from .literary_ai import (canonical_sources, requested_book_count,
                          validate_recommendation_text, recommendation_sources)
from .local_llm import OllamaJSON
from .test_local_ai import SHOW, response
from .test_recommendation_grounding import IDEALS, LEGEND


class RequestedRecommendationCountTests(SimpleTestCase):
    def test_confirmed_alternate_titles_cannot_fill_two_recommendation_slots(self):
        from .test_literary_identity import BOOK
        from .literary_ai import distinct_work_records
        alias = {**BOOK, 'title': 'Papelucho y el marciano'}
        sources = canonical_sources([BOOK, alias])
        self.assertEqual(len(distinct_work_records(sources)), 1)
        selected = recommendation_sources(sources, 2)
        self.assertEqual(len([s for s in selected if s['kind'] == 'book']), 1)

    def test_plain_one_book_answer_must_include_the_actual_author(self):
        sources = canonical_sources([IDEALS])
        draft = {'text': 'Puedes leer Ideals of the East, de Dan Brown.',
                 'books': [{'title': IDEALS['title'], 'author': IDEALS['author'], 'source_id': 1}]}
        with self.assertRaisesRegex(ValueError, 'autor real'):
            validate_recommendation_text(draft, sources)

    def test_cards_alone_cannot_hide_an_empty_recommendation_in_the_message(self):
        sources = canonical_sources([IDEALS, LEGEND])
        draft = {'text': '¡Buen tema! Aquí tienes tres obras clave.',
                 'books': [{'title': source['title'], 'author': source['author'], 'source_id': source['id']}
                           for source in sources]}
        with self.assertRaisesRegex(ValueError, 'título de cada obra'):
            validate_recommendation_text(draft, sources)

    def test_one_book_limits_visible_candidates_and_keeps_only_its_bound_evidence(self):
        sources = canonical_sources([IDEALS, LEGEND,
            {**IDEALS, 'kind': 'web', 'title': IDEALS['title'],
             'identity_text': IDEALS['title'] + ' ' + IDEALS['author'],
             'url': 'https://openlibrary.org/works/OL1W'}])
        selected = recommendation_sources(sources, 1)
        self.assertEqual([s['title'] for s in selected if s['kind'] == 'book'], [IDEALS['title']])
        self.assertEqual(len(selected), 2)
        self.assertEqual([s['id'] for s in selected], [1, 2])

    def test_more_options_excludes_books_already_recommended(self):
        sources = canonical_sources([IDEALS, LEGEND])
        selected = recommendation_sources(sources, 3, excluded=[IDEALS])
        self.assertEqual([s['title'] for s in selected], [LEGEND['title']])

    def test_distinct_authors_does_not_fill_a_list_with_the_same_author(self):
        sources = canonical_sources([IDEALS, {**IDEALS, 'title': 'Another verified work'}, LEGEND])
        selected = recommendation_sources(sources, 3, different_authors=True)
        self.assertEqual([s['title'] for s in selected], [IDEALS['title'], LEGEND['title']])

    def test_fewer_sources_never_creates_an_unverified_book(self):
        sources = canonical_sources([IDEALS])
        self.assertEqual(len(recommendation_sources(sources, 3)), 1)

    def schema_for(self, intent, count):
        sources = canonical_sources([IDEALS, LEGEND])
        book = sources[0]
        draft = {'status': 'answer', 'basis': 'sources',
                 'text': 'Una lectura sobre arte japonés.', 'citations': [book['id']],
                 'needs_web': False, 'books': [{'title': book['title'],
                     'author': book['author'], 'source_id': book['id']}]}
        data = {'intent': intent, 'requested_book_count': count,
                'sources': sources, 'require_book_sources': True}
        with patch('core.local_llm.read_json_url', side_effect=[SHOW, response({**draft, 'books': [book['id']]})]) as network:
            OllamaJSON()('answer', 'JSON', data, 'qwen3.5:9b-q4_K_M')
        return network.call_args.kwargs['payload']['format']

    def test_one_book_request_caps_the_generator_even_when_more_sources_exist(self):
        requested = requested_book_count('estoy buscando un libro sobre arte japones')
        self.assertEqual(requested, 1)
        schema = self.schema_for('recommend', requested)
        self.assertEqual(schema['properties']['books']['maxItems'], 1)
        self.assertEqual(schema['properties']['books']['items']['enum'], [1, 2])

    def test_count_is_not_applied_to_character_analysis(self):
        schema = self.schema_for('analysis', 1)
        self.assertNotEqual(schema['properties']['books'].get('maxItems'), 1)

    def test_spanish_and_numeric_counts_keep_their_requested_value(self):
        for message, expected in [('Recomiéndame tres libros sobre arte', 3),
                                  ('Quiero 2 novelas', 2), ('Busco una obra de historia', 1),
                                  ('Recomiéndame otros dos', 2), ('Dame dos más', 2),
                                  ('Dame solamente cinco', 5), ('Recomiéndame 2', 2),
                                  ('Recomiéndame libros de arte', None)]:
            with self.subTest(message=message):
                self.assertEqual(requested_book_count(message), expected)

    def test_three_text_options_cannot_masquerade_as_one_book_card(self):
        sources = canonical_sources([IDEALS, LEGEND])
        draft = {'text': '1. Ideals of the East — Okakura Kakuzō: Arte japonés.\n'
                         '2. Legend in Japanese art — Henri L. Joly: Leyendas japonesas.',
                 'books': [{'title': IDEALS['title'], 'author': IDEALS['author'], 'source_id': 1}]}
        with self.assertRaisesRegex(ValueError, 'mismas obras'):
            validate_recommendation_text(draft, sources)

    def test_one_text_option_and_one_matching_card_are_consistent(self):
        sources = canonical_sources([IDEALS, LEGEND])
        draft = {'text': '1. **Ideals of the East — Okakura Kakuzō**: Arte japonés.',
                 'books': [{'title': IDEALS['title'], 'author': IDEALS['author'], 'source_id': 1}]}
        validate_recommendation_text(draft, sources)

    def test_a_correct_card_cannot_hide_the_wrong_author_in_the_visible_list(self):
        sources = canonical_sources([IDEALS, LEGEND])
        draft = {'text': '1. Ideals of the East — Dan Brown: Arte japonés.',
                 'books': [{'title': IDEALS['title'], 'author': IDEALS['author'], 'source_id': 1}]}
        with self.assertRaisesRegex(ValueError, 'autor'):
            validate_recommendation_text(draft, sources)

    def test_a_title_subtitle_colon_does_not_hide_its_actual_author(self):
        book = {**IDEALS, 'title': 'Arte japonés: una introducción', 'author': 'Autora de prueba'}
        sources = canonical_sources([book])
        draft = {'text': '1. **Arte japonés: una introducción — Autora de prueba**: Arte japonés.',
                 'books': [{'title': book['title'], 'author': book['author'], 'source_id': 1}]}
        validate_recommendation_text(draft, sources)
