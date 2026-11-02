"""El esquema y el auditor exigen los mismos hechos, sin convertir cortesía en datos."""
import json
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from .literary_ai import canonical_sources
from .literary_quality import required_fact_statements, validate_audit
from .local_llm import OllamaJSON
from .test_local_ai import SHOW, response


HEADER = 'Aquí tienes tres obras clave para explorar la historia de Corea:'
FACT = 'A Concise History of Korea, de Michael J. Seth, está catalogado como historia coreana.'
QUESTION = '¿Te interesa algún periodo histórico o un aspecto cultural en particular?'
PLAN = {'questions': ['Recomiéndame libros sobre historia de Corea'], 'search_queries': [],
        'needs_contents': False, 'needs_fresh_sources': False, 'spoilers_requested': False}
SOURCES = canonical_sources([{
    'kind': 'book', 'title': 'A Concise History of Korea', 'author': 'Michael J. Seth',
    'source': 'Open Library', 'url': 'https://openlibrary.org/works/OL8442432W',
    'description': 'Temas del catálogo: History, Korea, History, Korea, civilization.',
    'categories': ['History', 'Korea'],
}])


def draft(text):
    return {'status': 'answer', 'basis': 'sources', 'text': text, 'needs_web': False,
            'citations': [1], 'books': [{'title': SOURCES[0]['title'],
                'author': SOURCES[0]['author'], 'source_id': 1}]}


def checked(statement, evidence='History, Korea'):
    return {'decision': 'approve', 'only_books': True,
            'coverage': [{'question_id': 1, 'status': 'answered'}],
            'claims': [{'statement': statement, 'verdict': 'supported',
                        'source_id': 1, 'evidence': evidence}],
            'search_queries': [], 'issues': []}


class RequiredFactContractTests(SimpleTestCase):
    def test_narrow_presentational_header_and_final_question_are_not_factual_claims(self):
        text = '¡Buen tema! ' + HEADER + '\n\n1. ' + FACT + '\n\n' + QUESTION
        self.assertEqual(required_fact_statements(text), [FACT])
        audit = checked(FACT)
        self.assertEqual(validate_audit(audit, PLAN, draft(text), SOURCES,
                                        PLAN['questions'][0], strict_facts=True), audit)

    def test_header_with_a_date_period_or_added_assertion_still_requires_audit(self):
        headers = [
            'Aquí tienes tres obras clave para explorar la historia de Corea desde 1900:',
            'Aquí tienes tres obras clave para explorar la historia de Corea del siglo XX:',
            'Aquí tienes tres obras clave para explorar Corea, que fue un reino:',
            'Aquí tienes tres obras que fueron publicadas en 1900:',
        ]
        for header in headers:
            with self.subTest(header=header):
                self.assertEqual(required_fact_statements(header + '\n' + FACT), [header, FACT])
                with self.assertRaisesRegex(ValueError, 'todas las frases'):
                    validate_audit(checked(FACT), PLAN, draft(header + '\n' + FACT), SOURCES,
                                   PLAN['questions'][0], strict_facts=True)

    def test_a_heading_cannot_hide_a_factual_sentence_after_its_colon(self):
        text = HEADER + ' La obra fue publicada originalmente en 1950.'
        self.assertEqual(required_fact_statements(text), [text])

    def test_final_question_cannot_replace_a_missing_factual_check(self):
        text = HEADER + '\n' + FACT + '\n' + QUESTION
        audit = checked(QUESTION)
        audit['claims'][0].update(verdict='inference', source_id=0, evidence='')
        with self.assertRaisesRegex(ValueError, 'todas las frases'):
            validate_audit(audit, PLAN, draft(text), SOURCES, PLAN['questions'][0], strict_facts=True)

    def test_strict_schema_enumerates_exactly_the_same_required_facts(self):
        text = '¡Buen tema! ' + HEADER + '\n1. ' + FACT + '\n' + QUESTION
        audit = checked(FACT, SOURCES[0]['description'])
        for flag in ('all_factual_claims_required', 'specific_factual_question'):
            with self.subTest(flag=flag):
                client = OllamaJSON()
                def local_response(url, **kwargs):
                    if url.endswith('/api/show'):
                        return SHOW
                    context = json.loads(kwargs['payload']['messages'][1]['content'])
                    proof_id = next(key for key, proof in context['audit_evidence_pool'].items()
                                    if proof == {'source_id': 1, 'evidence': SOURCES[0]['description']})
                    return response({**audit, 'claims': {'c1': {'verdict': 'supported', 'proof_id': proof_id}}})
                fetch = Mock(side_effect=local_response)
                data = {'message': PLAN['questions'][0], 'draft': draft(text),
                        'sources': SOURCES, 'plan': PLAN, flag: True}
                with patch('core.local_llm.read_json_url', fetch):
                    self.assertEqual(client('audit', 'Solo JSON', data, 'qwen3.5:4b-q4_K_M'), audit)
                schema = fetch.call_args.kwargs['payload']['format']['properties']['claims']
                self.assertEqual(schema['type'], 'object')
                self.assertEqual(schema['required'], ['c1'])
                self.assertFalse(schema['additionalProperties'])
                for alternative in schema['properties']['c1']['anyOf']:
                    self.assertEqual(set(alternative['properties']), {'verdict', 'proof_id'})
                context = json.loads(fetch.call_args.kwargs['payload']['messages'][1]['content'])
                self.assertEqual(context['audit_required_claims'], {'c1': FACT})


class IdentityEvidenceBoundaryTests(SimpleTestCase):
    def test_simple_title_and_author_identity_can_use_bibliographic_identity(self):
        statement = 'A Concise History of Korea es un libro de Michael J. Seth.'
        audit = checked(statement, SOURCES[0]['title'])
        self.assertEqual(validate_audit(audit, PLAN, draft(statement), SOURCES,
                                        PLAN['questions'][0], strict_facts=True), audit)

    def test_title_alone_cannot_support_a_specific_description_or_period(self):
        statements = [
            'A Concise History of Korea presenta una narración episódica de la civilización coreana.',
            'A Concise History of Korea explora las relaciones internacionales del siglo XX.',
            'A Concise History of Korea se publicó originalmente en 1950.',
        ]
        for statement in statements:
            with self.subTest(statement=statement):
                with self.assertRaisesRegex(ValueError, 'solo confirma identidad'):
                    validate_audit(checked(statement, SOURCES[0]['title']), PLAN,
                                   draft(statement), SOURCES, PLAN['questions'][0], strict_facts=True)

    def test_title_fragment_or_author_alone_does_not_prove_content(self):
        statement = 'A Concise History of Korea ofrece una narración detallada de la dinastía Joseon.'
        for evidence in ('History of Korea', SOURCES[0]['author']):
            with self.subTest(evidence=evidence), self.assertRaisesRegex(ValueError, 'solo confirma identidad'):
                validate_audit(checked(statement, evidence), PLAN, draft(statement), SOURCES,
                               PLAN['questions'][0], strict_facts=True)

    def test_real_descriptive_span_can_support_a_descriptive_claim(self):
        statement = 'A Concise History of Korea ofrece una narración cronológica de historia coreana.'
        evidence = 'El libro ofrece una narración cronológica de la historia de Corea.'
        sources = [{**SOURCES[0], 'description': SOURCES[0]['description'] + ' ' + evidence}]
        audit = checked(statement, evidence)
        self.assertEqual(validate_audit(audit, PLAN, draft(statement), sources,
                                        PLAN['questions'][0], strict_facts=True), audit)

    def test_year_in_the_real_title_is_still_a_simple_identity(self):
        statement = '1984 es un libro de George Orwell.'
        sources = canonical_sources([{'kind': 'book', 'title': '1984', 'author': 'George Orwell',
            'source': 'Catálogo LitMate', 'description': 'Ficha de prueba sin sinopsis.'}])
        answer = {**draft(statement), 'books': [{'title': '1984', 'author': 'George Orwell', 'source_id': 1}]}
        audit = checked(statement, 'George Orwell')
        self.assertEqual(validate_audit(audit, PLAN, answer, sources,
                                        PLAN['questions'][0], strict_facts=True), audit)


class CatalogueDescriptionBoundaryTests(SimpleTestCase):
    def test_subject_tags_do_not_prove_an_episodic_or_academic_approach(self):
        for detail in ('presenta una narración episódica de la civilización coreana',
                       'ofrece una narrativa cronológica y fragmentada',
                       'adopta una perspectiva académica y filosófica',
                       'describe la vida cotidiana del siglo XIX'):
            statement = SOURCES[0]['title'] + ' ' + detail + '.'
            with self.subTest(detail=detail), self.assertRaisesRegex(ValueError, 'materias del catálogo'):
                validate_audit(checked(statement), PLAN, draft(statement), SOURCES,
                               PLAN['questions'][0], strict_facts=True)

    def test_catalogue_with_a_real_synopsis_can_support_a_descriptive_style(self):
        statement = SOURCES[0]['title'] + ' ofrece una narrativa cronológica de historia coreana.'
        proof = 'This book provides a chronological narrative of Korean history.'
        sources = [{**SOURCES[0], 'synopsis': proof,
                    'description': SOURCES[0]['description'] + '\nSinopsis del registro bibliográfico: ' + proof}]
        audit = checked(statement, proof)
        self.assertEqual(validate_audit(audit, PLAN, draft(statement), sources,
                                        PLAN['questions'][0], strict_facts=True), audit)

    def test_period_explicitly_listed_in_english_metadata_is_supported(self):
        statement = SOURCES[0]['title'] + ' aborda la historia coreana del siglo XX.'
        proof = 'Temas del catálogo: History, Korea, 20th Century.'
        sources = [{**SOURCES[0], 'description': proof,
                    'categories': ['History', 'Korea', '20th Century']}]
        audit = checked(statement, proof)
        self.assertEqual(validate_audit(audit, PLAN, draft(statement), sources,
                                        PLAN['questions'][0], strict_facts=True), audit)

    def test_missing_period_or_year_cannot_be_added_to_general_history_tags(self):
        for detail in ('aborda la historia coreana del siglo XX', 'se publicó originalmente en 1950'):
            statement = SOURCES[0]['title'] + ' ' + detail + '.'
            with self.subTest(detail=detail), self.assertRaisesRegex(ValueError, 'materias del catálogo'):
                validate_audit(checked(statement), PLAN, draft(statement), SOURCES,
                               PLAN['questions'][0], strict_facts=True)

    def test_descriptive_web_page_is_not_restricted_to_catalogue_subjects(self):
        statement = SOURCES[0]['title'] + ' presenta una narración episódica.'
        proof = 'La obra presenta una narración episódica de su materia.'
        sources = [{**SOURCES[0], 'kind': 'web', 'description': proof,
                    'read_mode': 'pasaje de página pública'}]
        audit = checked(statement, proof)
        self.assertEqual(validate_audit(audit, PLAN, draft(statement), sources,
                                        PLAN['questions'][0], strict_facts=True), audit)
