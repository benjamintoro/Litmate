"""Held-out identity patterns, frozen after development on synthetic names.

These are controlled linguistic fixtures using different literary entities,
not quotations or independently verified literary facts. Live coverage is
measured separately through evaluar_chat_http.py and its captured sources.
"""
from django.test import SimpleTestCase

from .ai_character_answers import answer_from_sources, request_for
from .test_character_quality_regression import evidence
from .literary_memory import _character_aliases


CASES = (
    ('fantasy', 'El hobbit', 'J. R. R. Tolkien', 'Gollum', 'Sméagol', 'Bilbo Bolsón', 'enemigo'),
    ('classic', 'Oliver Twist', 'Charles Dickens', 'Jack Dawkins', 'Artful Dodger', 'Oliver Twist', 'compañero'),
    ('latin_american', 'Rayuela', 'Julio Cortázar', 'Lucía', 'La Maga', 'Horacio Oliveira', 'amiga'),
    ('contemporary', 'Matar un ruiseñor', 'Harper Lee', 'Arthur Radley', 'Boo', 'Jean Louise Finch', 'protector'),
    ('unfamiliar_fixture', 'Las rutas del estuario', 'Nora Ejemplo', 'Elena del Valle', 'Lena', 'Irene Sol', 'hermana'),
)


class CharacterAliasHoldoutTests(SimpleTestCase):
    def test_two_sided_identity_on_heldout_works(self):
        for category, title, author, canonical, alias, companion, relationship in CASES:
            with self.subTest(category=category):
                short_companion = companion.split()[0]
                role = 'También conocido como ' + alias + ', es ' + relationship + ' de ' + short_companion + '.'
                sources = evidence(title, author, [(canonical, role),
                    (companion, 'También llamado ' + short_companion + ', es un personaje principal de la obra.')])
                history = [{'accepted': True, 'books': sources[:1], 'sources': sources}]
                message = '¿Qué relación tienen ' + alias + ' y ' + companion + '?'
                result = answer_from_sources(message, request_for(message, history), sources)
                self.assertIsNotNone(result)
                self.assertIn(relationship + ' de ' + short_companion, result.text)
                self.assertTrue(result.diagnostics['audit']['claims'])

    def test_no_alias_from_negation_cooccurrence_or_unrelated_sentence(self):
        for passage in ('Elena no es conocida como Lena.',
                        'Elena es amiga de Lena.',
                        'Elena camina. Irene es conocida como Lena.',
                        'Elena, enemiga de Irene, es conocida como Lena.'):
            with self.subTest(passage=passage):
                self.assertEqual(_character_aliases('Elena', passage, ['Lena']), [])

    def test_parenthetical_names_keep_occupations_out(self):
        self.assertEqual(_character_aliases('Helena', 'Helena (Lena): es viajera.'), ['Lena'])
        self.assertEqual(_character_aliases('Helena', 'Helena (Protagonista): es viajera.'), [])

    def test_other_works_cannot_donate_alias_proofs(self):
        first = evidence('La primera obra', 'Autora A', [('Elena', 'Es amiga de Irene.')])
        second = evidence('La segunda obra', 'Autora B', [('Elena', 'También llamada Lena, es amiga de Irene.')])
        question = '¿Qué relación tienen Lena y Irene?'
        history = [{'accepted': True, 'books': first[:1], 'sources': first}]
        self.assertIsNone(answer_from_sources(question, request_for(question, history), [*first, *second]))
