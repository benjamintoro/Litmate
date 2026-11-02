"""Local reuse of literal mission evidence, not an assertion of success."""
from django.test import SimpleTestCase
from .test_character_quality_regression import evidence


class GoalEvidenceTests(SimpleTestCase):
    def sources(self):
        book, source = evidence('Las rutas', 'Autora Ejemplo', [])
        source['description'] = 'La novela narra el viaje de Elena para recuperar el mapa perdido de su familia.'
        source['identity_text'] = 'Las rutas es una novela de Autora Ejemplo. ' + source['description']
        return book, source

    def test_existing_goal_evidence_avoids_research_and_still_has_audit(self):
        from .ai_narrative_answers import goal_answer
        book, source = self.sources()
        history = [{'accepted': True, 'books': [book], 'sources': [source], 'question': 'Háblame de Las rutas', 'answer': ''}]
        result = goal_answer('¿Quién debía recuperar el mapa?', history)
        self.assertIsNotNone(result)
        self.assertIn('Elena', result.text)
        self.assertEqual(result.diagnostics['audit']['decision'], 'approve')

    def test_goal_is_not_proof_of_a_completed_action_or_different_object(self):
        from .ai_narrative_answers import goal_answer
        book, source = self.sources()
        history = [{'accepted': True, 'books': [book], 'sources': [source], 'question': '', 'answer': ''}]
        self.assertIsNone(goal_answer('¿Quién recuperó el mapa?', history))
        self.assertIsNone(goal_answer('¿Quién debía recuperar la corona?', history))
