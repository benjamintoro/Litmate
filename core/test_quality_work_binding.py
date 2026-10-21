"""Pruebas controladas: una cita literal de otra obra no confirma el dato."""
from django.test import SimpleTestCase

from .literary_ai import canonical_sources
from .literary_quality import validate_audit


PLAN = {'questions': ['Recomiéndame libros de arte japonés'], 'search_queries': [],
        'needs_contents': False, 'needs_fresh_sources': False, 'spoilers_requested': False}
TEA_PROOF = 'Esta obra explora la ceremonia del té y su relación con la estética japonesa.'
SOURCES = canonical_sources([
    {'kind': 'book', 'title': 'Ideals of the East', 'author': 'Okakura Kakuzō',
     'source': 'Open Library', 'url': 'https://openlibrary.org/works/OL7095110W',
     'description': 'Temas del catálogo: Art, Japanese; Art, Asia; Japan.',
     'categories': ['Art, Japanese', 'Japan']},
    {'kind': 'book', 'title': 'The Book of Tea', 'author': 'Okakura Kakuzō',
     'source': 'Open Library', 'url': 'https://openlibrary.org/works/OL54172W',
     'description': TEA_PROOF, 'synopsis': TEA_PROOF},
])


def answer(statement):
    return {'status': 'answer', 'basis': 'sources', 'text': statement,
            'citations': [1, 2], 'needs_web': False,
            'books': [{'title': source['title'], 'author': source['author'],
                       'source_id': source['id']} for source in SOURCES]}


def audit(statement, *, source_id=2, proof=TEA_PROOF):
    return {'decision': 'approve', 'only_books': True,
            'coverage': [{'question_id': 1, 'status': 'answered'}],
            'claims': [{'statement': statement, 'verdict': 'supported',
                        'source_id': source_id, 'evidence': proof}],
            'search_queries': [], 'issues': []}


class WorkBoundClaimTests(SimpleTestCase):
    def validate(self, statement, *, sources=SOURCES, source_id=2, proof=TEA_PROOF):
        return validate_audit(audit(statement, source_id=source_id, proof=proof), PLAN,
                              answer(statement), sources, PLAN['questions'][0], strict_facts=True)

    def test_actual_passage_of_same_author_other_book_cannot_verify_a_claim(self):
        statement = 'Ideals of the East explica la ceremonia del té y la estética japonesa.'
        with self.assertRaisesRegex(ValueError, 'otra obra'):
            self.validate(statement)

    def test_correct_work_can_use_its_own_descriptive_passage(self):
        statement = 'The Book of Tea explora la ceremonia del té y la estética japonesa.'
        self.assertEqual(self.validate(statement)['decision'], 'approve')

    def test_comparative_claim_can_cite_a_relevant_work(self):
        statement = ('A diferencia de Ideals of the East, The Book of Tea explora '
                     'la ceremonia del té y su estética.')
        self.assertEqual(self.validate(statement)['decision'], 'approve')

    def test_evidence_explicitly_bound_to_wrong_book_is_rejected(self):
        statement = 'Ideals of the East explica la ceremonia del té y la estética japonesa.'
        sources = [SOURCES[0], {**SOURCES[1], 'kind': 'web',
                    'title': 'Una página de literatura', 'author': 'Editorial',
                    'work_title': SOURCES[1]['title'], 'work_author': SOURCES[1]['author'],
                    'work_binding_verified': True}]
        with self.assertRaisesRegex(ValueError, 'otra obra'):
            self.validate(statement, sources=sources)

    def test_web_page_bound_to_correct_book_preserves_its_provenance(self):
        statement = 'The Book of Tea explica la ceremonia del té y la estética japonesa.'
        sources = [SOURCES[0], {**SOURCES[1], 'kind': 'web',
                    'title': 'Una página de literatura', 'author': 'Editorial',
                    'work_title': SOURCES[1]['title'], 'work_author': SOURCES[1]['author'],
                    'work_binding_verified': True}]
        self.assertEqual(self.validate(statement, sources=sources)['decision'], 'approve')

    def test_general_comparative_web_page_is_not_mistaken_for_a_different_book(self):
        statement = 'The Book of Tea explora la ceremonia del té y la estética japonesa.'
        sources = [SOURCES[0], {**SOURCES[1], 'kind': 'web',
                    'title': 'Comparación de obras de Okakura', 'author': 'Editorial'}]
        self.assertEqual(self.validate(statement, sources=sources)['decision'], 'approve')

    def test_same_title_with_explicit_different_author_is_not_the_same_work(self):
        proof = 'Historia documentada del mundo antiguo y sus poblaciones.'
        sources = canonical_sources([
            {'kind': 'book', 'title': 'Historia', 'author': 'Autora Primera',
             'source': 'Catálogo LitMate', 'description': proof},
            {'kind': 'book', 'title': 'Historia', 'author': 'Autor Segundo',
             'source': 'Catálogo LitMate', 'description': proof},
        ])
        statement = 'Historia, de Autora Primera, describe el mundo antiguo.'
        with self.assertRaisesRegex(ValueError, 'otra obra'):
            self.validate(statement, sources=sources, proof=proof)
        self.assertEqual(self.validate(statement, sources=sources, source_id=1,
                                        proof=proof)['decision'], 'approve')

    def test_longest_specific_saga_title_does_not_bind_to_short_collection_title(self):
        proof = 'Papelucho se encuentra con un marciano llamado Det.'
        sources = canonical_sources([
            {'kind': 'book', 'title': 'Papelucho', 'author': 'Marcela Paz',
             'source': 'Catálogo LitMate', 'description': proof},
            {'kind': 'book', 'title': 'Papelucho y el marciano', 'author': 'Marcela Paz',
             'source': 'Catálogo LitMate', 'description': proof},
        ])
        statement = 'Papelucho y el marciano presenta al marciano Det.'
        with self.assertRaisesRegex(ValueError, 'otra obra'):
            self.validate(statement, sources=sources, source_id=1, proof=proof)
        self.assertEqual(self.validate(statement, sources=sources,
                                        proof=proof)['decision'], 'approve')

    def test_confirmed_bibliographic_alias_binds_to_the_same_work(self):
        proof = 'Papelucho conoce a un marciano llamado Det.'
        canonical = 'Diario secreto de Papelucho y el marciano'
        alias = 'Papelucho y el marciano'
        source = {'kind': 'book', 'title': canonical, 'author': 'Marcela Paz',
                  'source': 'Open Library', 'url': 'https://openlibrary.org/works/OL1W',
                  'description': proof,
                  'confirmed_aliases': [{'title': alias,
                    'source_url': 'https://openlibrary.org/works/OL1W',
                    'evidence': canonical + ' también se edita como ' + alias + '.'}]}
        sources = canonical_sources([source])
        statement = alias + ' presenta al marciano Det.'
        self.assertEqual(self.validate(statement, sources=sources, source_id=1,
                                        proof=proof)['decision'], 'approve')

    def test_metadata_copied_to_synopsis_fields_still_does_not_verify_style(self):
        proof = 'Temas del catálogo: History, Korea, civilization.'
        statement = 'A history of Korea ofrece una narración episódica de historia coreana.'
        for field in ('synopsis', 'research_summary'):
            with self.subTest(field=field):
                sources = canonical_sources([{'kind': 'book', 'title': 'A history of Korea',
                    'author': 'Kyung Moon Hwang', 'source': 'Open Library',
                    'description': proof, field: proof}])
                with self.assertRaisesRegex(ValueError, 'materias del catálogo'):
                    self.validate(statement, sources=sources, source_id=1, proof=proof)

    def test_original_real_catalogue_failure_is_rejected(self):
        proof = 'Temas del catálogo: History, Korea, civilization, Civilization, Korea, history'
        statement = ('A history of Korea — Kyung Moon Hwang: Presenta una narración '
                     'episódica de la historia coreana, enfocándose en los aspectos civiles '
                     'y políticos a través de un enfoque accesible.')
        sources = canonical_sources([{'kind': 'book', 'title': 'A history of Korea',
            'author': 'Kyung Moon Hwang', 'source': 'Open Library', 'description': proof,
            'read_mode': 'ficha bibliográfica; materias de catálogo, no texto de la obra'}])
        with self.assertRaisesRegex(ValueError, 'materias del catálogo'):
            self.validate(statement, sources=sources, source_id=1, proof=proof)
