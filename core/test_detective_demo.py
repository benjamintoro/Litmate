"""Fallos reales de la experiencia completa, con obras sintéticas."""
from unittest.mock import Mock
from django.test import SimpleTestCase
from .test_related_recommendation_cards import book, history
from .test_narrative_answers import BOOK, PAGE
from .literary_ai import canonical_sources


class DetectiveDemoTests(SimpleTestCase):
    def test_tell_more_about_ordinal_selects_the_recommended_work_before_generation(self):
        from .ai_narrative_answers import request_for
        from .literary_focus import prepare_focus
        first, second = book('Primer destino', 'Elena Robles'), book('Segundo destino', 'Irene Sol', identifier=2)
        turns = history(first) + [{'accepted': True, 'question': 'Recomiéndame dos libros',
            'intent': 'recommend', 'books': [first, second], 'sources': [first, second]}]
        request = request_for('Cuéntame más del segundo', turns)
        self.assertIsNotNone(request)
        self.assertEqual(request['title'], second['title'])
        state = {'turns': turns, 'active_work': first}
        prepare_focus(state, 'Cuéntame más del segundo')
        self.assertEqual(state['active_work']['title'], second['title'])

    def test_ordinal_overview_reuses_its_received_synopsis_without_catalogue_lookup(self):
        from unittest.mock import patch
        from .ai_quick_answers import quick_answer
        first = book('Primer destino', 'Elena Robles')
        second = book('Segundo destino', 'Irene Sol', identifier=2)
        second['description'] = 'Una viajera recorre las montañas para recuperar el mapa de su familia.'
        turns = [{'accepted': True, 'question': 'Recomiéndame dos libros', 'intent': 'recommend',
                  'books': [first, second], 'sources': [first, second]}]
        with patch('core.ai_quick_answers.quick_knowledge_sources', return_value=[]) as lookup:
            result = quick_answer('Cuéntame más del segundo', turns)
        self.assertIsNotNone(result)
        self.assertEqual(result.books[0]['title'], second['title'])
        self.assertIn(second['description'], result.text)
        lookup.assert_not_called()

        # También las tarjetas del modelo Libro, cuya procedencia interna no
        # se convierte artificialmente en una URL externa.
        second.update(source='Catálogo LitMate', url='', book_id='db_77')
        result = quick_answer('Cuéntame más del segundo', turns)
        self.assertIsNotNone(result)
        self.assertEqual(result.books[0]['title'], second['title'])
        self.assertNotIn('Fuentes', result.text)

    def test_adult_and_standalone_preferences_cannot_accept_a_childrens_series(self):
        from .literary_constraints import recommendation_constraints, constraints_match
        constraints = recommendation_constraints('Recomiéndame dos libros para adultos y sin sagas')
        wrong = book('Una aventura infantil', 'Elena Robles', ['Juvenile Fiction'])
        wrong['description'] = 'La primera entrega de una serie de aventuras.'
        good = book('Una vida distinta', 'Irene Sol', ['Fiction'])
        good['description'] = 'Una novela autoconclusiva para lectores adultos.'
        self.assertFalse(constraints_match(wrong, constraints))
        self.assertTrue(constraints_match(good, constraints))
        unknown = book('Un viaje por el río', 'Irene Sol', ['Fiction'])
        unknown['description'] = 'Una historia de viajes y amistad.'
        self.assertFalse(constraints_match(unknown, recommendation_constraints('Libros para adultos')))
    def test_relationship_relative_clause_identifies_both_people(self):
        from .ai_character_answers import _relationship_fact
        fact = {'name': 'Clara', 'role': 'Amiga que Ana conoce en la estación.', 'aliases': []}
        self.assertTrue(_relationship_fact(fact, ['Clara', 'Ana']))
        self.assertFalse(_relationship_fact({**fact, 'role': 'Amiga que Irene conoce y presenta a Ana.'}, ['Clara', 'Ana']))

    def test_symbolic_objects_are_not_narrative_roles_but_personified_objects_are(self):
        from .ai_character_answers import _facts
        roles = [('Ana', 'Es la protagonista que explora la estación.'),
                 ('Las torres', 'son las emociones y tareas comunes del día a día.'),
                 ('Las algas', 'son los malos hábitos y pensamientos, según la moraleja del autor.'),
                 ('La brújula', 'la protección, los celos o los mimos.'),
                 ('El espejo', 'se trata del ego y de la vanidad.'),
                 ('El cofre', 'Es un cofre que habla y acompaña a Ana.')]
        body = '\n'.join(name + ': ' + role for name, role in roles)
        page = {**PAGE, 'description': body, 'character_facts': [
            {'name': name, 'role': role, 'evidence': name + ': ' + role} for name, role in roles]}
        result = _facts({}, canonical_sources([page]))
        self.assertEqual([item['name'] for item in result], ['Ana', 'El cofre'])

    def test_links_followup_uses_the_active_verified_identity_without_searching(self):
        from .ai_quick_answers import book_links_answer
        base = book('El mapa de los bosques', 'Elena Robles')
        result = book_links_answer('¿Dónde puedo encontrarlo?', history(base))
        self.assertIsNotNone(result)
        self.assertEqual(result.books[0]['title'], base['title'])
        self.assertIn('disponibilidad', result.text)

    def test_read_and_rejected_ordinals_update_the_existing_private_recommendation_memory(self):
        from .genre_recommendations import reading_feedback_answer, remember_recommendations
        from .literary_ai import ChatResult
        first, second = book('Primer destino', 'Elena Robles'), book('Segundo destino', 'Irene Sol', identifier=2)
        turn = {'accepted': True, 'question': 'Recomiéndame dos libros', 'intent': 'recommend',
                'books': [first, second], 'sources': [first, second]}
        message = 'Ya leí el primero y no me interesa el segundo.'
        result = reading_feedback_answer(message, [turn])
        self.assertIsNotNone(result)
        self.assertNotEqual(result.status, 'rejected')
        state = {'turns': [turn]}
        remember_recommendations(state, message, {}, result)
        self.assertIn(first['title'], state['recommendations']['read_titles'])
        self.assertIn(second['title'], state['recommendations']['rejected_titles'])

    def test_similar_language_preference_and_more_options_keep_the_verified_reference(self):
        from .ai_related_recommendations import related_recommendation_answer
        base = book('Los mapas de la amistad', 'Elena Robles', ['Friendship', 'Fiction'])
        first = book('Amigos en la costa', 'Irene Sol', ['Friendship', 'Fiction'], 2)
        first['language'] = 'es'
        search = Mock(return_value=[first])
        result = related_recommendation_answer('Recomiéndame dos libros similares en español', history(base), search)
        self.assertIsNotNone(result)
        self.assertIn('español', search.call_args_list[0].args[0])

    def test_trusted_local_identity_can_use_bound_narrative_topics(self):
        from unittest.mock import patch
        from .literary_knowledge import ORIGINAL_LICENSE
        from .ai_related_recommendations import related_recommendation_answer
        base = {**BOOK, 'source': 'Conocimiento literario local', 'license': ORIGINAL_LICENSE,
                'categories': [], 'description': 'Cuaderno lunar, de Ana Robles.'}
        page = {**PAGE, 'work_binding_verified': True, 'work_title': base['title'],
                'work_author': base['author'], 'description': 'Esta novela explora la amistad entre viajeros.'}
        turns = history(base)
        turns[0]['sources'].append(page)
        option = book('Amigos del mar', 'Irene Sol', ['Friendship', 'Fiction'], 3)
        with patch('core.ai_quick_answers._bundled', return_value=[base]):
            result = related_recommendation_answer('Otro similar', turns, Mock(return_value=[option]))
        self.assertIsNotNone(result)

    def test_clue_explanation_reuses_received_evidence_without_claiming_uniqueness(self):
        from .ai_identification_details import identification_explanation_answer
        base = book('El mapa de los bosques', 'Elena Robles')
        base['description'] = 'Una viajera encuentra un mapa en una estación lunar abandonada.'
        turns = history(base)
        turns[0].update(intent='identify', question='Recuerdo una viajera con un mapa en una estación lunar.')
        result = identification_explanation_answer('¿Qué pistas te hicieron pensar en ese libro?', turns)
        self.assertIsNotNone(result)
        self.assertIn('mapa', result.text)
        self.assertNotIn('única en la literatura', result.text)
        self.assertEqual(result.diagnostics['model_calls'], 0)

    def test_unresolved_ordinal_feedback_is_not_stored_as_an_invented_title(self):
        from .genre_recommendations import reading_feedback_answer, remember_recommendations
        base = book('Una sola lectura', 'Elena Robles')
        turns = history(base)
        turns[0]['intent'] = 'recommend'
        message = 'Ya leí el primero y no me interesa el segundo'
        result = reading_feedback_answer(message, turns)
        state = {'turns': turns}
        remember_recommendations(state, message, {}, result)
        self.assertEqual(state['recommendations']['rejected_titles'], [])

    def test_more_similar_options_cannot_fall_through_to_an_unrelated_catalogue_search(self):
        from unittest.mock import patch
        from .literary_ai_views import _compute_answer_impl
        base = book('Los mapas de la amistad', 'Elena Robles', ['Friendship', 'Fiction'])
        context = {'recommendation_state': {'related_reference': base, 'constraints': {'language': 'es'}}}
        with patch('core.ai_related_recommendations.related_recommendation_answer', return_value=None), \
             patch('core.literary_ai_views._model_answer', side_effect=AssertionError('Lost reference')), \
             patch('core.ai_character_answers.character_answer', return_value=None):
            result, client = _compute_answer_impl('Dame otras dos opciones', history(base), context)
        self.assertFalse(result.books)
        self.assertEqual(result.status, 'clarification')
        self.assertEqual(client.calls, 0)

    def test_a_merged_catalogue_record_reloads_only_the_original_curated_metadata(self):
        from unittest.mock import patch
        from .literary_knowledge import ORIGINAL_LICENSE
        from .ai_related_recommendations import related_recommendation_answer
        base = {**BOOK, 'source': 'Conocimiento literario local', 'license': ORIGINAL_LICENSE,
                'categories': ['Friendship', 'Fiction'], 'description': 'Un viaje que explora la amistad.'}
        merged = {**base, 'source': 'Conocimiento literario local / Wikidata',
                  'categories': ['Cooking'], 'description': 'Texto que no procede de la ficha original.'}
        turns = history(merged)
        option = book('Amigos del mar', 'Irene Sol', ['Friendship', 'Fiction'], 3)
        with patch('core.ai_quick_answers._bundled', return_value=[base]):
            result = related_recommendation_answer('Otro similar', turns, Mock(return_value=[option]))
        self.assertIsNotNone(result)
        self.assertNotIn('cooking', result.diagnostics['shared_catalogue_subjects'])
