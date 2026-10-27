"""Regresiones de atribución: literalidad de una cita no demuestra su remitente.

El caso Frankenstein procede del original Gutenberg 84, capítulo 7; los otros
ejemplos son frases sintéticas para comprobar la regla sin respuestas por obra.
No se consultan fuentes remotas ni se llama a Ollama.
"""
from django.test import SimpleTestCase

from .literary_quality import validate_audit


NEWS = ('“William is dead!—that sweet child, whose smiles delighted and warmed\n'
        'my heart, who was so gentle, yet so gay! Victor, he is murdered!')
FATHER = 'On my return, I found the following letter from my father:—'


def validate_statement(statement, proof, body=None):
    source = {'id': 1, 'kind': 'excerpt', 'title': 'Frankenstein',
              'author': 'Mary Wollstonecraft Shelley',
              'description': body or proof, 'url': 'https://www.gutenberg.org/ebooks/84',
              'source': 'Original autorizado de prueba', 'locator': 'Chapter 7'}
    draft = {'status': 'answer', 'basis': 'sources', 'text': statement,
             'citations': [1], 'books': [], 'needs_web': False}
    plan = {'questions': ['¿Qué noticia comunica la carta?'], 'search_queries': [],
            'needs_contents': True, 'needs_fresh_sources': False, 'spoilers_requested': False}
    audit = {'decision': 'approve', 'only_books': True,
             'claims': [{'statement': statement, 'source_id': 1,
                         'verdict': 'supported', 'evidence': proof}],
             'coverage': [{'question_id': 1, 'status': 'answered'}],
             'issues': [], 'search_queries': []}
    return validate_audit(audit, plan, draft, [source], plan['questions'][0], strict_facts=True)


class SubjectAttributionAuditTests(SimpleTestCase):
    def test_real_news_quote_does_not_identify_elizabeth_as_the_letter_writer(self):
        statement = ('En la carta que Elizabeth Lavenza escribe a Victor Frankenstein, '
                     'le comunica la noticia de que William ha sido asesinado.')
        with self.assertRaisesRegex(ValueError, 'remitente|atribuci|papel|sujeto'):
            validate_statement(statement, NEWS)

    def test_a_literal_letter_from_father_does_not_support_a_named_female_writer(self):
        with self.assertRaisesRegex(ValueError, 'remitente|atribuci|papel|sujeto'):
            validate_statement('Elizabeth escribe una carta a Victor.', FATHER)

    def test_news_can_be_reported_without_adding_an_unbacked_writer(self):
        result = validate_statement('La carta comunica que William ha sido asesinado.', NEWS)
        self.assertEqual(result['decision'], 'approve')

    def test_same_names_in_other_clauses_do_not_establish_the_sender(self):
        proof = 'Ana wrote the letter to Bruno. Clara read it aloud.'
        with self.assertRaisesRegex(ValueError, 'remitente|atribuci|papel|sujeto'):
            validate_statement('Clara escribió la carta a Bruno.', proof)

    def test_sender_and_recipient_are_not_interchangeable(self):
        proof = 'Ana sent a letter to Bruno.'
        with self.assertRaisesRegex(ValueError, 'remitente|atribuci|papel|sujeto'):
            validate_statement('Bruno envió una carta a Ana.', proof)

    def test_positive_sender_paraphrase_can_translate_the_action(self):
        result = validate_statement('Ana escribió una carta a Bruno.', 'Ana wrote a letter to Bruno.')
        self.assertEqual(result['decision'], 'approve')

    def test_received_letter_keeps_the_other_person_as_sender(self):
        proof = 'Bruno received a letter from Ana.'
        result = validate_statement('Bruno recibió una carta de Ana.', proof)
        self.assertEqual(result['decision'], 'approve')

    def test_anonymous_father_can_stay_anonymous_in_a_faithful_paraphrase(self):
        result = validate_statement('El padre de Victor le escribe una carta.', FATHER)
        self.assertEqual(result['decision'], 'approve')

    def test_a_negated_letter_action_cannot_be_approved_as_positive(self):
        with self.assertRaisesRegex(ValueError, 'remitente|atribuci|papel|sujeto'):
            validate_statement('Ana escribió una carta a Bruno.', 'Ana did not write the letter to Bruno.')

    def test_book_authorship_keeps_its_existing_bibliographic_contract(self):
        result = validate_statement('Ana escribió Jardín azul.', 'Jardín azul, de Ana.')
        self.assertEqual(result['decision'], 'approve')

    def test_writing_a_poem_in_another_clause_does_not_make_a_letter_sender(self):
        proof = 'Ana wrote a letter to Bruno. Clara wrote a poem to Bruno.'
        with self.assertRaisesRegex(ValueError, 'remitente|atribuci|papel|sujeto'):
            validate_statement('Clara escribió una carta a Bruno.', proof)

    def test_people_with_same_given_name_and_different_surnames_are_distinct(self):
        with self.assertRaisesRegex(ValueError, 'remitente|atribuci|papel|sujeto'):
            validate_statement('Ana Robles escribió una carta a Bruno.',
                               'Ana Ríos wrote a letter to Bruno.')

    def test_published_name_abbreviation_can_support_full_name_in_same_role(self):
        result = validate_statement('Ana Ríos escribió una carta a Bruno López.',
                                    'Ana wrote a letter to Bruno.')
        self.assertEqual(result['decision'], 'approve')

    def test_passive_voice_preserves_both_correspondence_roles(self):
        result = validate_statement('Ana escribió una carta a Bruno.',
                                    'The letter was written by Ana to Bruno.')
        self.assertEqual(result['decision'], 'approve')

    def test_a_different_object_in_the_same_sentence_cannot_donate_a_sender(self):
        for proof in ('Ana sent a poem to Bruno while Clara wrote the letter.',
                      'Ana wrote a poem about the letter to Bruno.',
                      'Ana sent a poem to Bruno and Clara wrote a letter to Bruno.'):
            with self.subTest(proof=proof), self.assertRaisesRegex(ValueError, 'remitente|atribuci|papel|sujeto'):
                validate_statement('Ana envió una carta a Bruno.', proof)

    def test_letter_read_by_another_person_does_not_prove_a_letter_writer(self):
        with self.assertRaisesRegex(ValueError, 'remitente|atribuci|papel|sujeto'):
            validate_statement('Ana escribió la carta.',
                               'Ana wrote a poem while Bruno read the letter.')

    def test_received_poem_does_not_become_a_letter_in_a_later_clause(self):
        with self.assertRaisesRegex(ValueError, 'remitente|atribuci|papel|sujeto'):
            validate_statement('Bruno recibió una carta de Ana.',
                               'Bruno received a poem while Clara read the letter from Ana.')

    def test_the_actual_sender_in_a_later_clause_remains_usable(self):
        result = validate_statement('Clara escribió una carta a Bruno.',
            'Ana sent a poem to Bruno while Clara wrote a letter to Bruno.')
        self.assertEqual(result['decision'], 'approve')

    def test_relative_letter_object_keeps_sender_and_recipient(self):
        result = validate_statement('La carta que Ana escribió a Bruno comunica la noticia.',
            'The letter that Ana wrote to Bruno conveyed the news.')
        self.assertEqual(result['decision'], 'approve')
