"""Corregir una referencia ausente no aprueba ni completa hechos generados."""
import copy

from django.test import SimpleTestCase

from .ai_recommendation_provenance import validate_recommendation_provenance
from .literary_quality import required_fact_statements, validate_audit


TITLE = 'The Last Colony'
AUTHOR = 'John Scalzi'
SUMMARY = ('John Perry y Jane Sagan aceptan dirigir una nueva colonia extraterrestre '
           'llamada Roanoke y viajan hacia ella.')
STATEMENT = f'**{TITLE} — {AUTHOR}**: Dos dirigentes aceptan dirigir una colonia extraterrestre.'
PLAN = {'questions': ['Recomienda una novela espacial'], 'search_queries': [],
        'needs_contents': False, 'needs_fresh_sources': False, 'spoilers_requested': False}


def sources():
    url = 'https://en.wikipedia.org/wiki/The_Last_Colony'
    return [
        {'id': 3, 'kind': 'book', 'title': TITLE, 'author': AUTHOR,
         'description': 'Temas del catálogo: Space warfare, Science fiction, Space colonies',
         'source': 'Open Library', 'url': 'https://openlibrary.org/works/OL12345W',
         'research_summary': SUMMARY, 'synopsis_source_url': url},
        {'id': 4, 'kind': 'web', 'title': TITLE, 'author': 'Fuente web',
         'description': SUMMARY, 'url': url, 'work_title': TITLE, 'work_author': AUTHOR,
         'work_binding_verified': True, 'read_mode': 'pasaje de página pública'},
    ]


def draft(text=STATEMENT, citations=None):
    return {'status': 'answer', 'text': text, 'basis': 'sources',
            'citations': [3] if citations is None else citations,
            'needs_web': False,
            'books': [{'title': TITLE, 'author': AUTHOR, 'source_id': 3}]}


def alternative(**changes):
    return {**sources()[1], 'id': 7,
            'url': 'https://editorial.example.test/the-last-colony', **changes}


class RecommendationProvenanceTests(SimpleTestCase):
    def test_missing_reference_reports_specific_title_card_and_available_page(self):
        with self.assertRaises(ValueError) as error:
            validate_recommendation_provenance(draft(), sources())
        message = str(error.exception)
        self.assertIn(TITLE, message)
        self.assertIn('ficha 3', message)
        self.assertIn('fuente web 4', message)
        self.assertIn('si no lo usas', message)
        self.assertIn('No añadas una referencia sin utilizar', message)

    def test_explicit_actual_page_citation_passes_without_mutating_any_input(self):
        answer, records = draft(citations=[3, 4]), sources()
        before = copy.deepcopy((answer, records))
        self.assertIsNone(validate_recommendation_provenance(answer, records))
        self.assertEqual((answer, records), before)

    def test_failure_does_not_add_missing_citation_or_rewrite_source(self):
        answer, records = draft(), sources()
        before = copy.deepcopy((answer, records))
        with self.assertRaises(ValueError):
            validate_recommendation_provenance(answer, records)
        self.assertEqual((answer, records), before)

    def test_catalogue_topic_and_identity_recommendations_do_not_require_web(self):
        for explanation in ('Una opción para explorar la ciencia ficción y el espacio.',
                            'Una novela de ciencia ficción sobre colonias espaciales.',
                            'Una opción para quienes buscan ciencia ficción espacial.'):
            answer = draft(f'**{TITLE} — {AUTHOR}**: {explanation}')
            with self.subTest(explanation=explanation):
                self.assertIsNone(validate_recommendation_provenance(answer, sources()))

    def test_title_actions_are_identity_and_do_not_become_plot_claims(self):
        records = sources()
        records[0]['title'] = 'La nave que descubre mundos'
        records[1].update(title=records[0]['title'], work_title=records[0]['title'])
        answer = draft(f'**{records[0]["title"]} — {AUTHOR}**: Una opción de ciencia ficción.')
        answer['books'][0]['title'] = records[0]['title']
        self.assertIsNone(validate_recommendation_provenance(answer, records))

    def test_real_catalogue_synopsis_is_not_mistaken_for_only_subjects(self):
        records = sources()
        records[0]['description'] += ' Sinopsis del registro bibliográfico: ' + SUMMARY
        self.assertIsNone(validate_recommendation_provenance(draft(), records))

    def test_tags_only_without_current_verified_map_are_left_to_existing_auditor(self):
        for change in ({'research_summary': ''}, {'synopsis_source_url': ''}):
            records = sources()
            records[0].update(change)
            with self.subTest(change=change):
                self.assertIsNone(validate_recommendation_provenance(draft(), records))
        self.assertIsNone(validate_recommendation_provenance(draft(), sources()[:1]))

    def test_another_verified_page_for_same_work_can_supply_cited_narrative(self):
        for mode in ('pasaje de página pública', 'extracto de introducción',
                     'pasaje de sección de artículo público'):
            records = sources() + [alternative(read_mode=mode)]
            with self.subTest(mode=mode):
                self.assertIsNone(validate_recommendation_provenance(draft(citations=[3, 7]), records))

    def test_snippet_unbound_injected_short_or_wrong_work_page_cannot_bypass(self):
        for changes in ({'read_mode': 'fragmento de buscador'}, {'work_binding_verified': False},
                        {'injection_detected': True}, {'description': 'Pocos datos.'},
                        {'work_title': 'Old Man’s War'}, {'work_author': 'Otro Autor'},
                        {'description': 'Temas del catálogo: Space colonies, Science fiction, '
                                        'Space warfare, Life on other planets'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_recommendation_provenance(draft(citations=[3, 7]), sources() + [alternative(**changes)])

    def test_valid_page_with_subjects_and_real_synopsis_is_not_rejected_as_tags_only(self):
        page = alternative(description='Temas del catálogo: Space colonies. Sinopsis editorial: ' + SUMMARY)
        self.assertIsNone(validate_recommendation_provenance(draft(citations=[3, 7]), sources() + [page]))

    def test_wrong_web_reference_or_unknown_identifier_cannot_cover_this_book(self):
        other = alternative(title='Otro libro', work_title='Otro libro')
        for citations in ([3, 7], [3, 99], [3, True]):
            with self.subTest(citations=citations), self.assertRaises(ValueError):
                validate_recommendation_provenance(draft(citations=citations), sources() + [other])

    def test_legitimate_same_work_local_excerpt_does_not_require_duplicate_web_citation(self):
        excerpt = {'id': 7, 'kind': 'excerpt', 'title': TITLE, 'author': AUTHOR,
                   'description': SUMMARY, 'source': 'Colección local: autorizado.pdf',
                   'book_id': 'chunk-123', 'read_mode': 'fragmento recuperado'}
        self.assertIsNone(validate_recommendation_provenance(draft(citations=[3, 7]), sources() + [excerpt]))

    def test_excerpt_label_alone_wrong_work_or_injection_is_not_local_evidence(self):
        excerpt = {'id': 7, 'kind': 'excerpt', 'title': TITLE, 'author': AUTHOR,
                   'description': SUMMARY, 'source': 'Colección local: autorizado.pdf',
                   'book_id': 'chunk-123', 'read_mode': 'fragmento recuperado'}
        for changes in ({'source': 'Buscador'}, {'book_id': ''}, {'read_mode': 'snippet'},
                        {'title': 'Otra obra'}, {'injection_detected': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_recommendation_provenance(draft(citations=[3, 7]),
                                                   sources() + [{**excerpt, **changes}])

    def test_unselected_or_unmentioned_mapped_book_does_not_require_extra_citation(self):
        unselected = draft()
        unselected['books'] = []
        self.assertIsNone(validate_recommendation_provenance(unselected, sources()))
        unmentioned = draft('La expedición descubre otro planeta y escapa de sus enemigos.')
        self.assertIsNone(validate_recommendation_provenance(unmentioned, sources()))

    def test_selected_other_book_with_its_own_synopsis_does_not_use_available_map(self):
        other = {'id': 8, 'kind': 'book', 'title': 'Otra expedición', 'author': 'Otra Autora',
                 'description': 'Una expedición descubre un mundo desconocido y regresa a la Tierra.'}
        answer = draft('**Otra expedición — Otra Autora**: Una expedición descubre un mundo desconocido.', [8])
        answer['books'] = [{'title': other['title'], 'author': other['author'], 'source_id': 8}]
        self.assertIsNone(validate_recommendation_provenance(answer, sources() + [other]))

    def test_numbered_heading_binds_description_on_next_line_without_repeating_title(self):
        answer = draft(f'1. **{TITLE} — {AUTHOR}**\n\nDos dirigentes aceptan dirigir una colonia extraterrestre.')
        with self.assertRaisesRegex(ValueError, TITLE):
            validate_recommendation_provenance(answer, sources())

    def test_numbered_other_work_description_is_not_assigned_to_mapped_book(self):
        other = {'id': 8, 'kind': 'book', 'title': 'Otra expedición', 'author': 'Otra Autora',
                 'description': 'Una expedición descubre un mundo desconocido.'}
        text = (f'1. **{TITLE} — {AUTHOR}**: Una opción para explorar la ciencia ficción.\n\n'
                '2. **Otra expedición — Otra Autora**\n\nUna expedición descubre otro planeta.')
        answer = draft(text, [3, 8])
        answer['books'].append({'title': other['title'], 'author': other['author'], 'source_id': 8})
        self.assertIsNone(validate_recommendation_provenance(answer, sources() + [other]))

    def test_other_volume_with_longer_title_is_not_confused_with_series_prefix(self):
        records = sources()
        other = {'id': 8, 'kind': 'book', 'title': TITLE + ': Another Adventure', 'author': AUTHOR,
                 'description': 'Una expedición descubre otro planeta.'}
        text = f'**{other["title"]} — {AUTHOR}**: Una expedición descubre otro planeta.'
        answer = draft(text, [3, 8])
        answer['books'].append({'title': other['title'], 'author': AUTHOR, 'source_id': 8})
        self.assertIsNone(validate_recommendation_provenance(answer, records + [other]))

    def test_multiple_available_pages_are_identified_using_current_ids(self):
        records = sources() + [alternative()]
        records[2]['url'] = records[0]['synopsis_source_url']
        with self.assertRaisesRegex(ValueError, 'fuente web 4, 7'):
            validate_recommendation_provenance(draft(), records)

    def test_correct_citation_does_not_prevent_real_auditor_rejecting_invented_evidence(self):
        answer, records = draft(citations=[3, 4]), sources()
        self.assertIsNone(validate_recommendation_provenance(answer, records))
        statement = required_fact_statements(answer['text'])[0]
        audit = {'decision': 'approve', 'only_books': True,
                 'coverage': [{'question_id': 1, 'status': 'answered'}],
                 'claims': [{'statement': statement, 'verdict': 'supported', 'source_id': 4,
                             'evidence': 'Un villano destruye Marte con una nave invisible.'}],
                 'search_queries': [], 'issues': []}
        with self.assertRaises(ValueError):
            validate_audit(audit, PLAN, answer, records, PLAN['questions'][0], strict_facts=True)

    def test_citing_web_does_not_promote_catalogue_tags_to_plot_evidence_in_auditor(self):
        answer, records = draft(citations=[3, 4]), sources()
        self.assertIsNone(validate_recommendation_provenance(answer, records))
        audit = {'decision': 'approve', 'only_books': True,
                 'coverage': [{'question_id': 1, 'status': 'answered'}],
                 'claims': [{'statement': required_fact_statements(answer['text'])[0],
                             'verdict': 'supported', 'source_id': 3,
                             'evidence': records[0]['description']}],
                 'search_queries': [], 'issues': []}
        with self.assertRaisesRegex(ValueError, 'materias del catálogo no prueban acontecimientos'):
            validate_audit(audit, PLAN, answer, records, PLAN['questions'][0], strict_facts=True)

    def test_nonanswers_and_malformed_unrelated_inputs_defer_to_existing_validation(self):
        for answer in (None, {}, {**draft(), 'status': 'clarify'}, {**draft(), 'status': 'refuse'},
                       {**draft(), 'books': None}, {**draft(), 'citations': None}):
            with self.subTest(answer=answer):
                self.assertIsNone(validate_recommendation_provenance(answer, sources()))
