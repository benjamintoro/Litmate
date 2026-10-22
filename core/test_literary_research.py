"""Suficiencia y candidatos se calculan desde evidencia recibida, sin búsquedas."""
from django.test import SimpleTestCase

from .literary_research import (assess_evidence, public_research_queries,
                                rank_candidates, resolve_verified_request)
from .test_literary_identity import BOOK, PUBLIC


class LiteraryResearchTests(SimpleTestCase):
    def test_synopsis_is_not_character_or_scene_evidence(self):
        synopsis = {**BOOK, 'description': BOOK['description'] * 3}
        self.assertTrue(assess_evidence('¿De qué trata?', [synopsis], [BOOK])['sufficient'])
        for question in ('Dime los personajes', '¿Qué sucede con Det?', 'Describe la escena del viaje'):
            result = assess_evidence(question, [synopsis], [BOOK])
            self.assertFalse(result['sufficient'])
            self.assertTrue(result['queries'])

    def test_character_roles_require_literal_support_and_correct_work(self):
        self.assertTrue(assess_evidence('Dime los personajes', [BOOK, PUBLIC], [BOOK])['sufficient'])
        invented = {**PUBLIC, 'character_facts': [{'name': 'Inventado', 'role': 'Rol que no existe'}]}
        self.assertFalse(assess_evidence('Dime los personajes', [BOOK, invented], [BOOK])['sufficient'])
        other = {**PUBLIC, 'title': 'Papelucho perdido'}
        self.assertFalse(assess_evidence('Dime los personajes', [BOOK, other], [BOOK])['sufficient'])

    def test_verified_facts_can_support_events_and_detect_conflict(self):
        source = {**PUBLIC, 'description': 'Det se queda con Papelucho durante el viaje.',
                  'literary_facts': [{'subject': 'Det', 'relation': 'ending', 'value': 'Se queda',
                      'topic': 'events', 'evidence': 'Det se queda con Papelucho durante el viaje.'}]}
        self.assertTrue(assess_evidence('¿Qué sucede con Det?', [BOOK, source], [BOOK])['sufficient'])
        other = {**source, 'description': 'Det abandona a Papelucho durante el viaje.',
                 'literary_facts': [{'subject': 'Det', 'relation': 'ending', 'value': 'Se va',
                     'topic': 'events', 'evidence': 'Det abandona a Papelucho durante el viaje.'}]}
        result = assess_evidence('¿Qué sucede con Det?', [source, other], [BOOK])
        self.assertTrue(result['contradictory'])
        self.assertFalse(result['sufficient'])

    def test_missing_character_is_not_a_contradiction(self):
        result = assess_evidence('Dime los personajes', [PUBLIC, {**PUBLIC, 'character_facts': PUBLIC['character_facts'][:1]}], [BOOK])
        self.assertFalse(result['contradictory'])

    def test_literal_conflicting_kinship_roles_need_more_evidence(self):
        from .literary_identity import bind_source
        first = {**PUBLIC, 'description': 'Ana: Es la hermana de Bruno.',
                 'character_facts': [{'name': 'Ana', 'role': 'Es la hermana de Bruno.'}]}
        second = {**PUBLIC, 'description': 'Ana: Es la madre de Bruno.',
                  'character_facts': [{'name': 'Ana', 'role': 'Es la madre de Bruno.'}]}
        # Conserva identidad del artículo, no el nombre del editor de la página.
        first = bind_source({**first, 'identity_text': PUBLIC['identity_text']}, BOOK)
        second = bind_source({**second, 'identity_text': PUBLIC['identity_text']}, BOOK)
        result = assess_evidence('Dime los personajes', [first, second], [BOOK])
        self.assertTrue(result['contradictory'])
        self.assertFalse(result['sufficient'])
        complementary = {**second, 'description': 'Ana: Es piloto de una nave.',
            'character_facts': [{'name': 'Ana', 'role': 'Es piloto de una nave.'}]}
        self.assertFalse(assess_evidence('Dime los personajes', [first, complementary], [BOOK])['contradictory'])

    def test_exact_quote_requires_verbatim_and_edition(self):
        self.assertFalse(assess_evidence('Dame una cita textual', [PUBLIC], [BOOK])['sufficient'])
        excerpt = {**BOOK, 'kind': 'excerpt', 'verbatim_verified': True, 'edition': 'Edición autorizada 2020'}
        self.assertTrue(assess_evidence('Dame una cita textual', [excerpt], [BOOK])['sufficient'])

    def test_queries_never_include_private_passage_or_personal_history(self):
        self.assertEqual(public_research_queries('Analiza este fragmento: texto privado', [BOOK]), [])
        self.assertEqual(public_research_queries('Mi nombre es Ana, mi correo es ana@example.com'), [])
        queries = public_research_queries('¿Y sus personajes? mi correo es ana@example.com', [BOOK])
        self.assertLessEqual(len(queries), 2)
        for query in queries:
            self.assertIn('Marcela Paz', query)
            self.assertNotIn('ana', query.lower())
            self.assertNotIn('correo', query)
        self.assertEqual(public_research_queries('Mi amigo Pedro recuerda un libro sobre una rosa'), [])
        self.assertEqual(public_research_queries('Recuerdo un libro, password es confidencial'), [])
        self.assertIn('Det', public_research_queries('¿Qué sucede con Det?', [BOOK])[0])

    def test_second_query_can_use_a_confirmed_title_alias_and_preserve_entity(self):
        queries = public_research_queries('¿Qué sucede con Det?', [BOOK])
        self.assertEqual(len(queries), 2)
        self.assertIn('Diario secreto de Papelucho y el marciano', queries[0])
        self.assertIn('"Papelucho y el marciano"', queries[1])
        for query in queries:
            self.assertIn('Marcela Paz', query)
            self.assertIn('Det', query)

    def test_unverified_title_alias_does_not_generate_a_second_query(self):
        book = {**BOOK, 'confirmed_aliases': [{'title': 'Papelucho perdido',
            'source_url': 'https://evil.example/', 'evidence': 'No confirma la obra.'}]}
        self.assertEqual(len(public_research_queries('¿Qué sucede con Det?', [book])), 1)

    def test_two_books_have_priority_over_alias_queries_within_total_limit(self):
        other = {'kind': 'book', 'title': 'El principito', 'author': 'Antoine de Saint-Exupéry'}
        queries = public_research_queries('Compara sus personajes', [BOOK, other])
        self.assertEqual(len(queries), 2)
        self.assertIn('Diario secreto', queries[0])
        self.assertIn('El principito', queries[1])

    def test_fact_about_another_character_does_not_answer_a_named_event(self):
        source = {**PUBLIC, 'description': 'Papelucho viaja durante el verano.',
                  'literary_facts': [{'subject': 'Papelucho', 'topic': 'events',
                                     'evidence': 'Papelucho viaja durante el verano.'}]}
        self.assertFalse(assess_evidence('¿Qué sucede con Det?', [source], [BOOK])['sufficient'])

    def test_vague_memories_request_clues_instead_of_searching(self):
        for message in ('Era un libro sobre una mujer que viajaba', 'Recuerdo una escena en un bosque y después viajaban',
                        'Recuerdo una escena de un libro, pero no su título'):
            result = assess_evidence(message, [], intent='identify')
            self.assertTrue(result['needs_clarification'])
            self.assertEqual(result['queries'], [])

    def test_known_memories_are_ranked_by_source_clues_not_hardcoded_answers(self):
        books = [{'kind': 'book', 'source': 'Conocimiento literario local', 'title': 'El principito',
                  'author': 'Antoine de Saint-Exupéry', 'description': 'Un niño vive en un planeta pequeño, cuida una rosa y conoce a un zorro.'},
                 {'kind': 'book', 'title': 'Rebelión en la granja', 'author': 'George Orwell',
                  'description': 'Una fábula política donde todos los animales son iguales.'},
                 {'kind': 'book', 'title': 'Crimen y castigo', 'author': 'Fiódor Dostoievski',
                  'description': 'Raskólnikov es el protagonista de esta novela.'}]
        cases = [('Recuerdo un niño que vivía en un planeta pequeño, tenía una rosa y conocía a un zorro', 'El principito'),
                 ('Recuerdo un libro donde decían que todos los animales son iguales', 'Rebelión en la granja'),
                 ('¿En qué libro aparece Raskolnikov?', 'Crimen y castigo')]
        for message, title in cases:
            with self.subTest(message=message):
                ranked = rank_candidates(message, books)
                self.assertEqual(ranked[0]['title'], title)
                self.assertTrue(ranked[0]['matched_clues'])
                self.assertTrue(assess_evidence(message, books, intent='identify')['sufficient'])
        changed = {**books[0], 'title': 'Una obra de prueba', 'author': 'Autora de prueba'}
        self.assertEqual(rank_candidates(cases[0][0], [changed])[0]['title'], 'Una obra de prueba')

    def test_same_words_in_other_volume_do_not_answer_selected_work(self):
        wrong = {**PUBLIC, 'title': 'Papelucho perdido'}
        self.assertFalse(assess_evidence('¿Quién es Det?', [wrong], [BOOK])['sufficient'])

    def test_weak_secondary_candidate_does_not_force_web_when_all_its_clues_are_already_supported(self):
        strong = {'kind': 'book', 'title': 'Una aventura espacial', 'author': 'Autora A',
                  'description': 'Un niño vive en un planeta pequeño, cuida una rosa y conoce un zorro.'}
        weak = {'kind': 'book', 'title': 'Otra aventura', 'author': 'Autora B',
                'description': 'Un visitante procede de otro planeta y conoce a una familia.'}
        message = 'Recuerdo un niño en un planeta pequeño que cuidaba una rosa y conocía un zorro'
        result = assess_evidence(message, [strong, weak], intent='identify')
        self.assertTrue(result['sufficient'])
        self.assertEqual(result['queries'], [])
        self.assertEqual([candidate['title'] for candidate in result['candidates']], [strong['title']])

    def test_comparable_candidates_keep_identification_uncertain(self):
        first = {'kind': 'book', 'title': 'Primera aventura', 'author': 'Autora A',
                 'description': 'Un niño vive en un planeta pequeño y cuida una rosa.'}
        second = {**first, 'title': 'Segunda aventura', 'author': 'Autora B'}
        result = assess_evidence('Recuerdo un niño en un planeta pequeño con una rosa', [first, second], intent='identify')
        self.assertFalse(result['sufficient'])
        self.assertEqual(len(result['candidates']), 2)

    def test_weaker_candidate_with_an_independent_clue_is_not_discarded(self):
        first = {'kind': 'book', 'title': 'Primera aventura', 'author': 'Autora A',
                 'description': 'Un niño vive en un planeta pequeño, cuida una rosa y conoce a un zorro.'}
        second = {'kind': 'book', 'title': 'Segunda aventura', 'author': 'Autora B',
                  'description': 'Una familia vive en un planeta donde cae nieve.'}
        result = assess_evidence('Recuerdo un niño en un planeta pequeño con una rosa, un zorro y nieve', [first, second], intent='identify')
        self.assertFalse(result['sufficient'])
        self.assertEqual(len(result['candidates']), 2)

    def test_no_research_for_conversation(self):
        self.assertTrue(assess_evidence('Hola, estoy cansada', [], intent='conversation')['sufficient'])


class VerifiedRequestTests(SimpleTestCase):
    def test_character_request_uses_canonical_identity_instead_of_router_guess(self):
        result = resolve_verified_request('Dime los personajes de Papelucho y el marciano', [BOOK, PUBLIC])
        self.assertEqual(result['intent'], 'analysis')
        self.assertEqual(result['books'][0]['title'], BOOK['title'])
        self.assertEqual(result['books'][0]['author'], 'Marcela Paz')
        self.assertTrue(result['books'][0]['work_id'])
        self.assertEqual(len(result['books'][0]['confirmed_aliases']), 1)

    def test_explicit_personajes_is_not_identification_even_if_router_mislabels(self):
        result = assess_evidence('Dime los personajes de Papelucho y el marciano', [BOOK, PUBLIC], [BOOK], intent='identify')
        self.assertEqual(result['requirements'], ['characters'])
        self.assertTrue(result['sufficient'])

    def test_no_previous_book_is_inferred_for_unknown_title_or_pronouns(self):
        for message in ('¿Y sus personajes?', '¿Qué sucede con Det?',
                        'Dime los personajes de Papelucho perdido',
                        'Dime los personajes de «Otro libro» como los de Papelucho y el marciano'):
            with self.subTest(message=message):
                self.assertEqual(resolve_verified_request(message, [BOOK, PUBLIC]), {'books': [], 'intent': ''})

    def test_unconfirmed_title_prefix_does_not_bind_another_volume(self):
        short = {**BOOK, 'title': 'Papelucho', 'confirmed_aliases': []}
        for question in ('Dime los personajes de Papelucho y el marciano',
                         'Dime los personajes principales del Papelucho y el marciano',
                         '¿Qué sucede con Det en Papelucho y el marciano?'):
            self.assertEqual(resolve_verified_request(question, [short])['books'], [])

    def test_remembered_title_still_requests_identification(self):
        result = resolve_verified_request('Recuerdo algo llamado Papelucho y el marciano, ¿es ese libro?', [BOOK])
        self.assertEqual(result['intent'], 'identify')
        self.assertEqual(result['books'][0]['author'], 'Marcela Paz')

    def test_ambiguous_authors_require_an_explicit_author(self):
        other = {**BOOK, 'author': 'Otra autora'}
        question = 'Dime los personajes de Papelucho y el marciano'
        self.assertEqual(resolve_verified_request(question, [BOOK, other])['books'], [])
        chosen = resolve_verified_request(question + ' de Marcela Paz', [BOOK, other])
        self.assertEqual(chosen['books'][0]['author'], 'Marcela Paz')

    def test_no_recommendation_or_comparison_is_replaced_with_reference_work(self):
        for message in ('Recomiéndame libros como Papelucho y el marciano',
                        'Compara Papelucho y el marciano con otra novela'):
            self.assertEqual(resolve_verified_request(message, [BOOK])['books'], [])

    def test_only_bibliographic_sources_can_correct_model_identity(self):
        invented = {**BOOK, 'source': 'Texto arbitrario sin verificación'}
        self.assertEqual(resolve_verified_request('Papelucho y el marciano', [invented])['books'], [])
        self.assertEqual(resolve_verified_request('Papelucho y el marciano', [PUBLIC])['books'], [])

    def test_multiple_explicit_books_do_not_create_an_arbitrary_active_work(self):
        other = {'kind': 'book', 'source': 'Conocimiento literario local',
                 'title': 'El principito', 'author': 'Antoine de Saint-Exupéry'}
        self.assertEqual(resolve_verified_request('Háblame de Papelucho y el marciano y El principito', [BOOK, other])['books'], [])

    def test_incidental_title_in_social_chat_does_not_change_personality(self):
        result = resolve_verified_request('Hoy estoy triste; ayer leí Papelucho y el marciano', [BOOK])
        self.assertEqual(result, {'books': [], 'intent': ''})
        self.assertEqual(resolve_verified_request('Papelucho y el marciano', [BOOK])['intent'], 'summary')

    def test_film_request_is_not_replaced_by_novel_metadata(self):
        self.assertEqual(resolve_verified_request('Dime los personajes de la película Papelucho y el marciano', [BOOK])['books'], [])
