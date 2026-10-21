"""Las fichas de arte japonés no prueban contenidos específicos de otra obra.

Identidades reales y metadatos mínimos controlados; ninguna prueba consulta
Internet, la base de usuarios o un modelo. El auditor simulado solo respalda
afirmaciones con un pasaje literal expresamente vinculado a esa afirmación.
"""
import copy
from unittest.mock import Mock

from django.test import SimpleTestCase

from .literary_ai import (LiteraryAssistant, canonical_sources, validate_draft,
                          validate_recommendation_text)
from .literary_evidence import validate_evidence
from .literary_quality import factual_statements, required_fact_statements, validate_audit
from .test_literary_ai import FakeLLM, ROUTE


IDEALS = {
    'kind': 'book', 'title': 'Ideals of the East', 'author': 'Okakura Kakuzō',
    'source': 'Open Library', 'url': 'https://openlibrary.org/works/OL7095110W',
    'description': 'Temas del catálogo: Art, Japanese; Art, Asia; Japan.',
    'categories': ['Art, Japanese', 'Art, Asia', 'Japan'],
    'read_mode': 'ficha bibliográfica; materias de catálogo, no texto de la obra',
}
LEGEND = {
    'kind': 'book', 'title': 'Legend in Japanese art', 'author': 'Henri L. Joly',
    'source': 'Open Library', 'url': 'https://openlibrary.org/works/OL182055W',
    'description': 'Temas del catálogo: Art, Japanese; Legends, Japan; Symbolism in art.',
    'categories': ['Art, Japanese', 'Legends, Japan', 'Symbolism in art'],
    'read_mode': 'ficha bibliográfica; materias de catálogo, no texto de la obra',
}
ARCHITECTURE = {
    'kind': 'book', 'title': 'The art and architecture of Japan',
    'author': 'Robert Treat Paine, Alexander Soper', 'source': 'Open Library',
    'url': 'https://openlibrary.org/works/OL9199187W',
    'description': 'Temas del catálogo: Art, Japanese; Architecture, Japan; History.',
    'categories': ['Art, Japanese', 'Architecture, Japan', 'History'],
    'read_mode': 'ficha bibliográfica; materias de catálogo, no texto de la obra',
}
DAVINCI = {
    'kind': 'book', 'title': 'The Da Vinci Code', 'author': 'Dan Brown',
    'source': 'Catálogo LitMate', 'book_id': 'fixture-davinci',
    'description': 'Novela de misterio que menciona obras de arte.',
    'categories': ['Fiction', 'Thriller'],
}
FAHRENHEIT = {
    'kind': 'book', 'title': 'Fahrenheit 451', 'author': 'Ray Bradbury',
    'source': 'Catálogo LitMate', 'book_id': 'fixture-fahrenheit',
    'description': 'Novela de ciencia ficción sobre una sociedad que quema libros.',
    'categories': ['Fiction', 'Science fiction'],
}
WEB_METADATA = {
    'kind': 'web', 'title': 'Registro bibliográfico de Ideals of the East',
    'author': 'Biblioteca', 'source': 'Página pública',
    'url': 'https://openlibrary.org/works/OL7095110W',
    'description': 'El registro relaciona Ideals of the East, de Okakura Kakuzō, con Art, Japanese.',
    'read_mode': 'contenido de ficha pública; no texto de la obra',
}
SUPPORTED = 'Ideals of the East, de Okakura Kakuzō, figura entre los libros de arte japonés.'
INVENTED = 'El libro explica la ceremonia del té y el diseño floral ikebana.'
PLAN = {'questions': ['Recomiéndame un libro sobre arte japonés'], 'search_queries': [],
        'needs_contents': False, 'needs_fresh_sources': False, 'spoilers_requested': False}


class GroundedRecommendationLLM(FakeLLM):
    def __init__(self, *, invented=False, omit_claim=False, invented_proof=False,
                 wrong_book=None, repair_correctly=False, multiple=False):
        super().__init__(route={**ROUTE, 'queries': ['arte japonés'], 'candidates': []})
        self.invented = invented
        self.omit_claim = omit_claim
        self.invented_proof = invented_proof
        self.wrong_book = wrong_book
        self.repair_correctly = repair_correctly
        self.multiple = multiple
        self.proofs = {SUPPORTED: (IDEALS['title'], 'Art, Japanese')}

    def __call__(self, stage, prompt, data, model):
        if stage not in {'answer', 'answer_web', 'repair', 'audit', 'plan'}:
            return super().__call__(stage, prompt, data, model)
        self.calls += 1
        self.records.append((stage, copy.deepcopy(data), model))
        if stage == 'plan':
            raise AssertionError('La recomendación temática usa un plan local, sin otra llamada de planificación.')
        if stage == 'audit':
            statements = required_fact_statements(data['draft']['text'])
            claims = []
            for statement in statements:
                proof = self.proofs.get(statement)
                source = next((source for source in data['sources'] if proof
                    and source['title'] == proof[0] and proof[1] in source.get('description', '')
                    and source['id'] in data['draft']['citations']), None)
                claims.append({'statement': statement, 'verdict': 'supported' if source else 'unverified',
                               'source_id': source['id'] if source else 0,
                               'evidence': proof[1] if source else ''})
            if self.omit_claim:
                claims = claims[:1]
            if self.invented_proof and len(claims) > 1:
                claims[1] = {**claims[1], 'verdict': 'supported',
                             'source_id': data['draft']['citations'][0],
                             'evidence': INVENTED}
            return {'decision': 'approve', 'only_books': True,
                    'coverage': [{'question_id': 1, 'status': 'answered'}],
                    'claims': claims, 'search_queries': [], 'issues': []}
        chosen = next(source for source in data['sources'] if source['title'] == IDEALS['title'])
        books = [chosen]
        text = SUPPORTED
        if self.multiple:
            books = [source for source in data['sources'] if source['kind'] == 'book'][:3]
            sentences = []
            for source in books:
                statement = source['title'] + ', de ' + source['author'] + ', está catalogado como arte japonés.'
                sentences.append(statement)
                self.proofs[statement] = (source['title'], 'Art, Japanese')
            text = '\n'.join(sentences)
        if self.invented and not (stage == 'repair' and self.repair_correctly):
            text += ' ' + INVENTED
        if self.wrong_book:
            text = self.wrong_book['title'] + ', de ' + self.wrong_book['author'] + ', es mi recomendación.'
            books = [{**self.wrong_book, 'id': chosen['id']}]
        return {'status': 'answer', 'basis': 'sources', 'text': text,
                'citations': [book['id'] for book in books], 'needs_web': False,
                'books': [{'title': book['title'], 'author': book['author'], 'source_id': book['id']}
                          for book in books]}


class RecommendationGroundingTests(SimpleTestCase):
    def build(self, *, fixtures=None, **options):
        llm = GroundedRecommendationLLM(**options)
        search = Mock(return_value=copy.deepcopy(fixtures or [IDEALS, WEB_METADATA]))
        bot = LiteraryAssistant(llm, search, quality_checks=True, fast_recommendations=True,
                                require_book_sources=True, research_enabled=True)
        return bot, llm, search

    def assert_grounded_replacement(self, result):
        """El texto rechazado no se publica: la ficha respalda otra respuesta."""
        self.assertEqual(result.status, 'answered', result.diagnostics)
        self.assertTrue(result.diagnostics.get('grounded_catalog_fallback'))
        self.assertTrue(result.diagnostics.get('validation_issues'), result.diagnostics)
        self.assertNotIn(INVENTED, result.text)
        self.assertNotIn('ceremonia del té', result.text)
        self.assertNotIn('ikebana', result.text)
        self.assertEqual(len(result.books), 1)
        self.assertEqual(result.books[0]['title'], IDEALS['title'])
        self.assertEqual(result.books[0]['author'], IDEALS['author'])
        self.assertEqual(len(result.sources), 1)
        source = result.sources[0]
        self.assertEqual(source['kind'], 'book')
        self.assertEqual(source['title'], IDEALS['title'])
        self.assertEqual(result.books[0]['source_id'], source['id'])
        final = {'status': 'answer', 'basis': 'sources', 'text': result.text,
                 'citations': [source['id']], 'needs_web': False, 'books': result.books}
        validate_draft(final, result.sources)
        validate_recommendation_text(final, result.sources)
        validate_evidence(final, result.sources, PLAN['questions'][0])
        audit = result.diagnostics['catalog_fallback_audit']
        self.assertEqual([claim['statement'] for claim in audit['claims']],
                         required_fact_statements(result.text))
        for claim in audit['claims']:
            self.assertEqual(claim['verdict'], 'supported')
            self.assertEqual(claim['source_id'], source['id'])
            self.assertIn(claim['evidence'], source['description'])
        validate_audit(audit, PLAN, final, result.sources,
                       PLAN['questions'][0], strict_facts=True)

    def test_catalogue_subjects_support_scope_without_inventing_book_contents(self):
        bot, llm, _ = self.build()
        result = bot.reply('Recomiéndame un libro sobre arte japonés')
        self.assertEqual(result.status, 'answered', result.diagnostics)
        self.assertTrue(result.diagnostics.get('grounded_recommendation'))
        self.assertIn('audit', [record[0] for record in llm.records])
        self.assertNotIn('review', [record[0] for record in llm.records])
        self.assertNotIn('plan', [record[0] for record in llm.records])
        answer = next(record[1] for record in llm.records if record[0] == 'answer')
        self.assertTrue(answer['all_factual_claims_required'])
        self.assertFalse(answer.get('specific_factual_question', False))
        self.assertEqual(len(answer['plan']['questions']), 1)

    def test_metadata_cannot_support_tea_or_ikebana_borrowed_from_another_book(self):
        bot, llm, _ = self.build(invented=True)
        result = bot.reply('Recomiéndame un libro sobre arte japonés')
        self.assert_grounded_replacement(result)
        self.assertNotIn('ceremonia del té', result.text)
        issues = result.diagnostics.get('validation_issues', [])
        self.assertTrue(any('sin respaldo' in issue['issue'] for issue in issues), issues)
        self.assertIn('audit', [record[0] for record in llm.records])

    def test_auditing_only_the_supported_first_sentence_cannot_hide_added_facts(self):
        bot, _, _ = self.build(invented=True, omit_claim=True)
        result = bot.reply('Recomiéndame un libro sobre arte japonés')
        self.assert_grounded_replacement(result)
        self.assertTrue(any('todas las frases' in issue['issue']
                            for issue in result.diagnostics.get('validation_issues', [])))

    def test_an_invented_literal_proof_is_rejected_even_if_auditor_says_supported(self):
        bot, _, _ = self.build(invented=True, invented_proof=True)
        result = bot.reply('Recomiéndame un libro sobre arte japonés')
        self.assert_grounded_replacement(result)
        self.assertTrue(any('prueba literal' in issue['issue']
                            for issue in result.diagnostics.get('validation_issues', [])))

    def test_repair_can_remove_unsupported_detail_and_publish_the_backed_recommendation(self):
        bot, llm, _ = self.build(invented=True, repair_correctly=True)
        result = bot.reply('Recomiéndame un libro sobre arte japonés')
        self.assertEqual(result.status, 'answered', result.diagnostics)
        self.assertNotIn('ceremonia del té', result.text)
        self.assertIn(IDEALS['title'], result.text)
        self.assertEqual(result.diagnostics['repairs'], 1)
        self.assertEqual([record[0] for record in llm.records].count('audit'), 2)
        self.assertFalse(result.diagnostics.get('grounded_catalog_fallback'))

    def test_wrong_topic_novels_do_not_survive_as_japanese_art_book_choices(self):
        fixtures = [DAVINCI, FAHRENHEIT, IDEALS, WEB_METADATA]
        for wrong_book in (DAVINCI, FAHRENHEIT):
            with self.subTest(title=wrong_book['title']):
                bot, llm, _ = self.build(fixtures=fixtures, wrong_book=wrong_book)
                result = bot.reply('Recomiéndame un libro sobre arte japonés')
                self.assert_grounded_replacement(result)
                answer = next(record[1] for record in llm.records if record[0] == 'answer')
                actual = {source['title'] for source in answer['sources'] if source['kind'] == 'book'}
                self.assertEqual(actual, {IDEALS['title']})
                self.assertNotIn(wrong_book['title'], result.text)

    def test_three_distinct_books_each_have_their_own_literal_subject_proof(self):
        bot, llm, _ = self.build(fixtures=[IDEALS, LEGEND, ARCHITECTURE], multiple=True)
        result = bot.reply('Recomiéndame tres libros sobre arte japonés')
        self.assertEqual(result.status, 'answered', result.diagnostics)
        self.assertEqual({book['title'] for book in result.books},
                         {IDEALS['title'], LEGEND['title'], ARCHITECTURE['title']})
        self.assertFalse(result.diagnostics.get('grounded_catalog_fallback'))
        audit = next(record[1] for record in llm.records if record[0] == 'audit')
        self.assertEqual(len(audit['draft']['books']), 3)
        self.assertTrue(audit['all_factual_claims_required'])

    def test_direct_strict_auditor_requires_literal_evidence_of_the_added_fact(self):
        sources = canonical_sources([IDEALS])
        draft = {'status': 'answer', 'basis': 'sources', 'text': SUPPORTED + ' ' + INVENTED,
                 'citations': [1], 'needs_web': False,
                 'books': [{'title': IDEALS['title'], 'author': IDEALS['author'], 'source_id': 1}]}
        audit = {'decision': 'approve', 'only_books': True,
                 'coverage': [{'question_id': 1, 'status': 'answered'}],
                 'claims': [{'statement': SUPPORTED, 'verdict': 'supported', 'source_id': 1,
                             'evidence': 'Art, Japanese'},
                            {'statement': INVENTED, 'verdict': 'unverified', 'source_id': 0,
                             'evidence': ''}], 'search_queries': [], 'issues': []}
        with self.assertRaisesRegex(ValueError, 'sin respaldo'):
            validate_audit(audit, PLAN, draft, sources, PLAN['questions'][0], strict_facts=True)

    def test_author_initial_is_not_a_second_factual_sentence(self):
        sources = canonical_sources([LEGEND])
        statement = 'Legend in Japanese art, de Henri L. Joly, está catalogado como arte japonés.'
        draft = {'status': 'answer', 'basis': 'sources', 'text': statement,
                 'citations': [1], 'needs_web': False,
                 'books': [{'title': LEGEND['title'], 'author': LEGEND['author'], 'source_id': 1}]}
        audit = {'decision': 'approve', 'only_books': True,
                 'coverage': [{'question_id': 1, 'status': 'answered'}],
                 'claims': [{'statement': statement, 'verdict': 'supported', 'source_id': 1,
                             'evidence': 'Art, Japanese'}], 'search_queries': [], 'issues': []}
        self.assertEqual(validate_audit(audit, PLAN, draft, sources, PLAN['questions'][0],
                                        strict_facts=True), audit)


class FactualStatementSegmentationTests(SimpleTestCase):
    def test_author_initials_and_following_sentence_have_separate_correct_bounds(self):
        for name in ('Henri L. Joly', 'Michael J. Seth', 'Fiódor M. Dostoievski', 'J. R. R. Tolkien'):
            with self.subTest(author=name):
                first = 'La obra fue escrita por ' + name + '.'
                second = 'Este segundo dato también requiere evidencia.'
                self.assertEqual(factual_statements(first + ' ' + second), [first, second])

    def test_abbreviations_and_markdown_numbering_preserve_literal_substrings(self):
        first = 'El Dr. Pérez cita al Sr. López como ejemplo, p. ej. en el prólogo.'
        second = '**La segunda obra** aborda otro tema verificable.'
        original = '1. ' + first + '\n2) ' + second
        statements = factual_statements(original)
        self.assertEqual(statements, [first, second])
        self.assertTrue(all(statement in original for statement in statements))

    def test_sentence_after_a_list_item_is_not_lost(self):
        first = 'Ideals of the East está catalogado como arte japonés.'
        second = 'El libro explica la ceremonia del té y el ikebana.'
        self.assertEqual(factual_statements('1. ' + first + ' ' + second), [first, second])

    def test_long_statement_is_not_truncated_before_its_unchecked_end(self):
        statement = 'Una afirmación ' + 'que requiere evidencia ' * 25 + 'termina con un dato inventado.'
        self.assertGreater(len(statement), 400)
        self.assertEqual(factual_statements(statement), [statement])
