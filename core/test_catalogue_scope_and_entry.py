"""El alcance y los párrafos de una lista conservan la obra que los respalda."""
from django.test import SimpleTestCase

from .literary_ai import canonical_sources
from .literary_quality import _claim_has_wrong_work, _unsupported_catalogue_detail
from .test_compact_audit_transport import CompactAuditTransportTests


CATALOGUE = {'kind': 'book', 'title': 'A History of Korea', 'author': 'Kyung Moon Hwang',
             'description': 'Temas del catálogo: History, Korea, civilization.',
             'categories': ['History', 'Korea', 'civilization']}


class CatalogueScopeTests(SimpleTestCase):
    def test_generic_subjects_do_not_verify_origins_present_or_completeness(self):
        for detail in ('desde sus orígenes hasta la actualidad', 'desde la antigüedad hasta el presente',
                       'ofrece un enfoque completo de la historia', 'abarca la historia actual'):
            with self.subTest(detail=detail):
                self.assertTrue(_unsupported_catalogue_detail('A History of Korea ' + detail + '.', CATALOGUE))

    def test_actual_subtitle_or_metadata_can_confirm_its_explicit_period(self):
        source = {**CATALOGUE, 'title': 'A History of Korea: From Antiquity to the Present'}
        self.assertFalse(_unsupported_catalogue_detail(source['title'] + ' aborda la antigüedad y el presente.', source))
        source = {**CATALOGUE, 'categories': ['History', 'Korea', 'Comprehensive', 'Origins', 'Present']}
        self.assertFalse(_unsupported_catalogue_detail('A History of Korea ofrece un enfoque completo desde sus orígenes hasta la actualidad.', source))


class NumberedEntryBindingTests(SimpleTestCase):
    def setUp(self):
        self.sources = canonical_sources([
            CATALOGUE,
            {'kind': 'book', 'title': 'A Concise History of Korea', 'author': 'Michael J. Seth',
             'description': 'Una historia del periodo antiguo.'},
            {'kind': 'book', 'title': 'The Two Koreas', 'author': 'Don Oberdorfer',
             'description': 'Una historia de las relaciones de las dos Coreas.'},
        ])
        self.statement = 'Este libro explica las relaciones de las dos Coreas.'
        self.draft = ('1. **A History of Korea — Kyung Moon Hwang**\n\n' + self.statement +
                      '\n\n2. **A Concise History of Korea — Michael J. Seth**\n\nUna historia del periodo antiguo.'
                      '\n\n3. **The Two Koreas — Don Oberdorfer**\n\nUna historia de relaciones.')

    def test_anonymous_description_cannot_take_another_entry_as_its_proof(self):
        self.assertTrue(_claim_has_wrong_work(self.statement, self.sources[2], self.sources, draft_text=self.draft))
        self.assertFalse(_claim_has_wrong_work(self.statement, self.sources[0], self.sources, draft_text=self.draft))

    def test_final_comparison_is_not_forced_to_the_last_numbered_entry(self):
        statement = 'En comparación, ambos enfoques exploran la historia de Corea.'
        text = self.draft + '\n\n' + statement
        self.assertFalse(_claim_has_wrong_work(statement, self.sources[0], self.sources, draft_text=text))

    def test_unknown_or_invalid_heading_does_not_fabricate_a_binding(self):
        for header in ('1. A History of Korea — Autor inventado', '1. Un título desconocido'):
            text = header + '\n\n' + self.statement
            self.assertFalse(_claim_has_wrong_work(self.statement, self.sources[2], self.sources, draft_text=text))

    def test_inline_description_then_blank_paragraph_ends_the_entry(self):
        statement = 'Ambos enfoques tienen diferencias.'
        text = '1. A History of Korea — Kyung Moon Hwang: Una historia general.\n\n' + statement
        self.assertFalse(_claim_has_wrong_work(statement, self.sources[2], self.sources, draft_text=text))


class CompactEntryOptionsTests(CompactAuditTransportTests):
    def test_compact_schema_excludes_another_work_for_a_pronominal_entry(self):
        context = self.context()
        statement = 'Este libro describe el cielo y las estrellas.'
        context['draft']['text'] = ('1. Libro del campo — Autor terrestre\n\n' + statement)
        result, captured = self.generate(context=context)
        slot = captured['payload']['format']['properties']['claims']['properties']['c2']['anyOf']
        allowed = [proof_id for choice in slot if choice['properties']['verdict'].get('const') == 'supported'
                   for proof_id in choice['properties']['proof_id']['enum']]
        pool = captured['input']['audit_evidence_pool']
        self.assertTrue(allowed)
        self.assertTrue(all(pool[proof_id]['source_id'] == 2 for proof_id in allowed))

