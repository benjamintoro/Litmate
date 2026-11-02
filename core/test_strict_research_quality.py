"""Regresiones de hechos y citas: no aprobar afirmaciones sin comprobarlas."""
from django.test import SimpleTestCase

from .literary_ai import canonical_sources
from .literary_evidence import validate_evidence
from .literary_quality import validate_audit


PLAN = {'questions': ['¿Qué sucede con Det?'], 'search_queries': [],
        'needs_contents': True, 'needs_fresh_sources': False, 'spoilers_requested': False}
FIRST = 'Det es amigo de Papelucho.'
SECOND = 'La convivencia ocasiona problemas y enfados.'
SOURCES = canonical_sources([{'kind': 'web', 'title': 'Ficha editorial', 'author': 'Fuente web',
    'url': 'https://literaturasm.cl/diario-secreto-de-papelucho-y-el-marciano/',
    'description': FIRST + ' ' + SECOND}])


def draft(text):
    return {'status': 'answer', 'basis': 'sources', 'text': text, 'citations': [1],
            'needs_web': False, 'books': []}


def claim(statement, verdict='supported'):
    return {'statement': statement, 'verdict': verdict,
            'source_id': 1 if verdict == 'supported' else 0,
            'evidence': statement if verdict == 'supported' else ''}


def audit(claims):
    return {'decision': 'approve', 'only_books': True,
            'coverage': [{'question_id': 1, 'status': 'answered'}],
            'claims': claims, 'search_queries': [], 'issues': []}


class StrictResearchAuditTests(SimpleTestCase):
    def test_first_supported_sentence_cannot_hide_an_unchecked_second_claim(self):
        answer = draft(FIRST + ' Det viaja realmente a Marte al terminar la historia.')
        with self.assertRaisesRegex(ValueError, 'todas las frases'):
            validate_audit(audit([claim(FIRST)]), PLAN, answer, SOURCES,
                           '¿Qué sucede con Det?', strict_facts=True)

    def test_each_supported_sentence_has_its_own_real_evidence(self):
        answer = draft(FIRST + ' ' + SECOND)
        checked = audit([claim(FIRST), claim(SECOND)])
        self.assertEqual(validate_audit(checked, PLAN, answer, SOURCES,
                                       '¿Qué sucede con Det?', strict_facts=True), checked)

    def test_checking_an_invention_as_unverified_still_cannot_approve_it(self):
        invented = 'Det viaja realmente a Marte al terminar la historia.'
        checked = audit([claim(FIRST), claim(invented, 'unverified')])
        with self.assertRaisesRegex(ValueError, 'sin respaldo'):
            validate_audit(checked, PLAN, draft(FIRST + ' ' + invented), SOURCES,
                           '¿Qué sucede con Det?', strict_facts=True)

    def test_explicit_uncertainty_can_accompany_a_supported_fact(self):
        uncertainty = 'No puedo confirmar qué sucede después con estas fuentes.'
        checked = audit([claim(FIRST), claim(uncertainty, 'unverified')])
        validate_audit(checked, PLAN, draft(FIRST + ' ' + uncertainty), SOURCES,
                       '¿Qué sucede con Det?', strict_facts=True)

    def test_auditor_cannot_supply_a_fabricated_evidence_span(self):
        checked = audit([claim(FIRST), claim(SECOND)])
        checked['claims'][1]['evidence'] = 'Una prueba inventada que nunca apareció en la página.'
        with self.assertRaisesRegex(ValueError, 'prueba literal'):
            validate_audit(checked, PLAN, draft(FIRST + ' ' + SECOND), SOURCES,
                           '¿Qué sucede con Det?', strict_facts=True)


class RememberedPassageEvidenceTests(SimpleTestCase):
    def setUp(self):
        self.sources = canonical_sources([{'kind': 'web', 'title': 'Rebelión en la granja',
            'author': 'Fuente web', 'description': 'La idea recordada es que todos los animales son iguales.',
            'read_mode': 'resumen factual original con procedencia; no texto de la novela',
            'url': 'https://www.penguinlibros.com/es/rebelion-en-la-granja/'}])

    def test_original_summary_does_not_certify_a_literal_novel_quote(self):
        answer = draft('La cita textual exacta de la novela es «todos los animales son iguales».')
        with self.assertRaisesRegex(ValueError, 'resumen original'):
            validate_evidence(answer, self.sources, '¿A qué obra pertenece esta frase?')

    def test_original_summary_can_identify_a_remembered_paraphrase(self):
        answer = draft('Tu recuerdo «todos los animales son iguales» apunta a Rebelión en la granja; lo trato como paráfrasis, sin confirmar una traducción exacta.')
        validate_evidence(answer, self.sources, '¿A qué obra pertenece esta frase?')

    def test_remembered_phrase_does_not_become_verified_wording_by_mentioning_memory(self):
        answer = draft("La frase que recuerdas, 'todos los animales son iguales', aparece como un mandamiento al principio.")
        with self.assertRaisesRegex(ValueError, 'resumen original'):
            validate_evidence(answer, self.sources, '¿A qué obra pertenece esta frase?')

    def test_quoting_the_readers_own_recollection_is_not_a_novel_quote(self):
        answer = draft("Basado en tu recuerdo de que 'todos los animales son iguales', la obra sugerida es Rebelión en la granja.")
        validate_evidence(answer, self.sources,
                          'Recuerdo un libro donde decían que todos los animales son iguales')

    def test_a_recollection_cannot_certify_where_the_quote_appears(self):
        answer = draft("La frase que recuerdas, 'todos los animales son iguales', aparece como un mandamiento al principio.")
        with self.assertRaisesRegex(ValueError, 'resumen original'):
            validate_evidence(answer, self.sources,
                              'Recuerdo un libro donde decían que todos los animales son iguales')

    def test_recollection_attribution_cannot_expand_the_readers_words(self):
        answer = draft("Basado en tu recuerdo de que 'todos los animales son iguales, con una continuación inventada', propongo esta obra.")
        with self.assertRaisesRegex(ValueError, 'no coincide'):
            validate_evidence(answer, self.sources,
                              'Recuerdo un libro donde decían que todos los animales son iguales')

    def test_exact_quote_request_cannot_be_satisfied_by_recollection(self):
        answer = draft("Basado en tu recuerdo de que 'todos los animales son iguales', esa es la frase.")
        with self.assertRaisesRegex(ValueError, 'resumen original'):
            validate_evidence(answer, self.sources,
                              'Recuerdo que todos los animales son iguales. Dame la cita textual exacta.')

    def test_single_curly_quotes_do_not_bypass_literal_verification(self):
        answer = draft('La obra dice ‘un pasaje completamente inventado que no recibimos’.')
        with self.assertRaisesRegex(ValueError, 'no coincide'):
            validate_evidence(answer, self.sources, '¿A qué obra pertenece esta frase?')

    def test_single_straight_quotes_do_not_bypass_literal_verification(self):
        answer = draft("La obra dice 'un pasaje completamente inventado que no recibimos'.")
        with self.assertRaisesRegex(ValueError, 'no coincide'):
            validate_evidence(answer, self.sources, '¿A qué obra pertenece esta frase?')

    def test_semantic_original_summary_does_not_certify_novel_wording(self):
        sources = [{**self.sources[0],
                    'read_mode': 'resumen original autorizado; no texto de la novela'}]
        answer = draft('La cita textual exacta es «todos los animales son iguales».')
        with self.assertRaisesRegex(ValueError, 'resumen original'):
            validate_evidence(answer, sources, '¿A qué obra pertenece esta frase?')

    def test_title_capitalization_is_not_mistaken_for_a_novel_quote(self):
        answer = draft('Tu recuerdo apunta a «Rebelión en la Granja», de George Orwell.')
        answer['books'] = [{'title': 'Rebelión en la granja', 'author': 'George Orwell',
                            'source_id': 1}]
        validate_evidence(answer, self.sources, '¿A qué obra pertenece esta frase?')

    def test_title_exemption_does_not_allow_a_fabricated_passage(self):
        answer = draft('En «Rebelión en la Granja» aparece «Un pasaje inexistente inventado aquí».')
        answer['books'] = [{'title': 'Rebelión en la granja', 'author': 'George Orwell',
                            'source_id': 1}]
        with self.assertRaisesRegex(ValueError, 'no coincide'):
            validate_evidence(answer, self.sources, '¿A qué obra pertenece esta frase?')
