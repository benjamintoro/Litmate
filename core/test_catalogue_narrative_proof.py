"""Materias bibliográficas no prueban eventos, aunque exista otra sinopsis."""
from django.test import SimpleTestCase

from .literary_ai import canonical_sources
from .literary_quality import _catalogue_only_proof_for_narrative, validate_audit
from . import test_compact_audit_transport as compact_fixtures


TAGS = 'Temas del catálogo: Space warfare, Science fiction, Life on other planets, Fiction, Space colonies.'
NARRATIVE = 'Dos líderes humanos aceptan dirigir una nueva colonia de otro planeta.'
EVENT = ('The Last Colony — John Scalzi: Dos líderes humanos aceptan dirigir una nueva '
         'colonia extraterrestre, enfrentándose a una flota invasora que exige rendición.')
SOURCE = {'kind': 'book', 'title': 'The Last Colony', 'author': 'John Scalzi',
          'description': TAGS, 'research_summary': NARRATIVE,
          'categories': ['Space warfare', 'Science fiction', 'Life on other planets', 'Fiction', 'Space colonies']}


class CatalogueNarrativeProofTests(SimpleTestCase):
    def test_tags_cannot_verify_real_failed_narrative_despite_an_additional_summary(self):
        self.assertTrue(_catalogue_only_proof_for_narrative(EVENT, SOURCE, TAGS))

    def test_each_catalogue_action_stays_distinct_from_its_subject(self):
        for action in ('acepta dirigir una colonia', 'se enfrenta a una flota invasora',
                       'descubre una amenaza', 'construye una nave', 'viaja a un planeta',
                       'exige la rendición del imperio', 'protege a una persona'):
            with self.subTest(action=action):
                self.assertTrue(_catalogue_only_proof_for_narrative('El protagonista ' + action + '.', SOURCE, TAGS))

    def test_actual_genre_and_subject_claims_can_use_catalogue_tags(self):
        for statement in ('The Last Colony es una novela de ciencia ficción espacial.',
                          'The Last Colony está catalogado en colonias espaciales.',
                          'Es una opción para explorar la temática espacial.'):
            with self.subTest(statement=statement):
                self.assertFalse(_catalogue_only_proof_for_narrative(statement, SOURCE, TAGS))

    def test_partial_category_span_cannot_verify_an_event(self):
        self.assertTrue(_catalogue_only_proof_for_narrative(EVENT, SOURCE, 'Space warfare, Science fiction'))

    def test_real_narrative_passage_remains_available(self):
        source = {**SOURCE, 'description': TAGS + ' Sinopsis del registro bibliográfico: ' + NARRATIVE}
        self.assertFalse(_catalogue_only_proof_for_narrative(EVENT, source, NARRATIVE))
        self.assertTrue(_catalogue_only_proof_for_narrative(EVENT, source, TAGS))

    def test_chunk_with_actual_synopsis_is_not_mistaken_for_pure_categories(self):
        proof = TAGS + ' Sinopsis del registro bibliográfico: ' + NARRATIVE
        self.assertFalse(_catalogue_only_proof_for_narrative(EVENT, {**SOURCE, 'description': proof}, proof))

    def test_title_words_are_not_interpreted_as_narrative_actions(self):
        source = {**SOURCE, 'title': 'Viaja a un planeta', 'author': 'Autora de prueba'}
        self.assertFalse(_catalogue_only_proof_for_narrative('Viaja a un planeta es ciencia ficción.', source, TAGS))

    def test_existing_validator_rejects_event_supported_only_by_tags(self):
        sources = canonical_sources([SOURCE])
        plan = {'questions': ['Recomiéndame una novela espacial']}
        draft = {'status': 'answer', 'text': EVENT, 'citations': [1]}
        audit = {'decision': 'approve', 'only_books': True,
                 'coverage': [{'question_id': 1, 'status': 'answered'}],
                 'claims': [{'statement': EVENT, 'verdict': 'supported', 'source_id': 1, 'evidence': TAGS}],
                 'search_queries': [], 'issues': []}
        with self.assertRaisesRegex(ValueError, 'acontecimientos de la trama'):
            validate_audit(audit, plan, draft, sources, plan['questions'][0], strict_facts=True)


class CompactNarrativeProofTests(SimpleTestCase):
    context = compact_fixtures.CompactAuditTransportTests.context
    generate = compact_fixtures.CompactAuditTransportTests.generate

    def test_compact_schema_cannot_select_pure_tags_as_event_evidence(self):
        context = self.context()
        context.update(sources=canonical_sources([SOURCE]))
        context['draft'].update(text=EVENT, citations=[1])
        result, captured = self.generate(context=context)
        choices = captured['payload']['format']['properties']['claims']['properties']['c1']['anyOf']
        self.assertFalse(any(choice['properties']['verdict'].get('const') == 'supported' for choice in choices))
        self.assertEqual(result['claims'][0]['verdict'], 'unverified')

    def test_compact_schema_keeps_actual_narrative_evidence(self):
        context = self.context()
        context.update(sources=canonical_sources([{**SOURCE, 'description': NARRATIVE, 'synopsis': NARRATIVE}]))
        context['draft'].update(text='The Last Colony: ' + NARRATIVE, citations=[1])
        result, captured = self.generate(context=context)
        self.assertEqual(result['claims'][0]['verdict'], 'supported')
        self.assertEqual(result['claims'][0]['evidence'], NARRATIVE)

