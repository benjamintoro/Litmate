"""Regresiones de identidad con pasajes controlados, sin HTTP ni hechos nuevos.

Los nombres y títulos de estas fuentes son fixtures lingüísticos. No acreditan
contenido de Wikipedia ni se incorporan a la memoria pública de la aplicación.
"""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from .ai_character_answers import (
    _profile_match, _profile_name_in, answer_from_sources, bind_character_profile,
)
from .literary_memory import remember_evidence, retrieve_character_entities
from .test_profile_depth import profile
from .test_character_quality_regression import evidence


class ProfileIdentityStabilizationTests(SimpleTestCase):
    def test_empty_name_is_not_a_profile_subject(self):
        self.assertFalse(_profile_name_in('', 'Cualquier texto.'))

    def test_middle_names_cannot_be_substituted_or_discarded(self):
        for canonical, other in (
            ('Ana María Sol', 'Ana Lucía Sol'),
            ('Juan del Valle', 'Juan de la Vega Valle'),
            ('Elena Sol', 'Elena conoce a Irene Sol'),
        ):
            with self.subTest(canonical=canonical):
                self.assertFalse(_profile_name_in(canonical, other))

    def test_exact_and_explicit_quoted_names_still_match(self):
        for canonical, text in (
            ('Ana María Sol', 'Ana María Sol es una viajera.'),
            ('Elena Sol', 'Elena "Lena" Sol es una viajera.'),
            ('Juan del Valle', 'Juan del «Norte» Valle es un viajero.'),
        ):
            with self.subTest(canonical=canonical):
                self.assertTrue(_profile_name_in(canonical, text))

    def test_a_similar_name_cannot_supply_a_profile_or_bind_a_work(self):
        page = profile()
        page.update(title='Ana María Sol',
                    identity_text='Ana Lucía Sol es un personaje de la novela Las rutas de Ana Escritora.',
                    description='Ana Lucía Sol es un personaje de la novela Las rutas de Ana Escritora.')
        self.assertFalse(_profile_match(page, ['Ana María Sol']))
        self.assertIsNone(bind_character_profile(page, {'title': 'Las rutas', 'author': 'Ana Escritora'}))
        request = {'task': 'character', 'focus': 'all', 'title': '', 'targets': [],
                   'names': ['Ana María Sol'], 'ambiguous': False}
        self.assertIsNone(answer_from_sources('¿Quién es Ana María Sol?', request, [page]))


def stored_page(facts):
    book, page = evidence('Los caminos del estuario', 'Autora de prueba', facts)
    page.update(work_title=book['title'], work_author=book['author'], work_binding_verified=True,
                storage_policy='wikipedia-cc-by-sa-4.0-v1', attribution={
                    'authors': 'Wikipedia contributors', 'title': page['title'], 'url': page['url'],
                    'revision_id': '1', 'license_url': 'https://creativecommons.org/licenses/by-sa/4.0/'})
    return book, page


class PersistentAliasStabilizationTests(SimpleTestCase):
    def retrieve(self, facts, names=()):
        book, page = stored_page(facts)
        with TemporaryDirectory() as folder:
            database = Path(folder) / 'memory.sqlite3'
            self.assertEqual(remember_evidence([book], [page], database=database)['sources'], 1)
            return retrieve_character_entities(books=[book], names=names, database=database)

    def test_shared_alias_does_not_merge_distinct_canonical_people(self):
        facts = [('Elena Alba', 'También llamada Lena, es la narradora del viaje.'),
                 ('Helena Ríos', 'También llamada Lena, es la antagonista del viaje.')]
        for requested in ((), ('Lena',)):
            for ordered in (facts, list(reversed(facts))):
                with self.subTest(requested=requested, ordered=ordered[0][0]):
                    entities = self.retrieve(ordered, requested)
                    self.assertEqual({e['canonical_name'] for e in entities}, {'Elena Alba', 'Helena Ríos'})
                    self.assertEqual(len({e['entity_id'] for e in entities}), 2)
                    for entity in entities:
                        self.assertEqual(entity['aliases'], ['Lena'])
                        self.assertEqual(len(entity['evidence']), 1)

    def test_ambiguous_alias_record_does_not_select_the_first_owner(self):
        facts = [('Elena Alba', 'También llamada Lena, es la narradora del viaje.'),
                 ('Helena Ríos', 'También llamada Lena, es la antagonista del viaje.'),
                 ('Lena', 'Es una viajera de identidad no precisada en este pasaje.')]
        entities = self.retrieve(facts, ('Lena',))
        self.assertEqual({e['canonical_name'] for e in entities}, {'Elena Alba', 'Helena Ríos', 'Lena'})

    def test_direct_published_equivalence_keeps_both_sources(self):
        entities = self.retrieve([
            ('Elena Alba', 'También llamada Lena, es la narradora del viaje.'),
            ('Lena', 'Es una viajera de la historia.'),
        ])
        self.assertEqual(len(entities), 1)
        self.assertEqual({entities[0]['name'], *entities[0]['aliases']}, {'Elena Alba', 'Lena'})
        self.assertEqual(len(entities[0]['evidence']), 2)

    def test_no_mutation_of_profile_sources(self):
        source = profile()
        before = deepcopy(source)
        self.assertIsNotNone(bind_character_profile(source, {'title': 'Las rutas', 'author': 'Ana Escritora'}))
        self.assertEqual(source, before)

    def test_a_shared_alias_cannot_donate_a_relationship(self):
        book, page = stored_page([
            ('Elena Alba', 'También llamada Lena, es la narradora del viaje.'),
            ('Helena Ríos', 'También llamada Lena, es la antagonista del viaje.'),
        ])
        page['description'] += '\nLa madre de Lena es Irene. La madre de Elena Alba es Rosa.'
        page['literary_facts'] = [
            {'subject': 'Lena', 'relation': 'mother', 'value': 'Irene',
             'topic': 'relationships', 'evidence': 'La madre de Lena es Irene.'},
            {'subject': 'Elena Alba', 'relation': 'mother', 'value': 'Rosa',
             'topic': 'relationships', 'evidence': 'La madre de Elena Alba es Rosa.'},
        ]
        with TemporaryDirectory() as folder:
            database = Path(folder) / 'memory.sqlite3'
            remember_evidence([book], [page], database=database)
            entities = retrieve_character_entities(books=[book], names=['Lena'],
                requirement='relationships', database=database)
        self.assertEqual(len(entities), 2)
        by_name = {entity['name']: entity for entity in entities}
        self.assertEqual([r['value'] for r in by_name['Elena Alba']['relations']], ['Rosa'])
        self.assertEqual(by_name['Helena Ríos']['relations'], [])


class IndependentIdentityPatternsTests(SimpleTestCase):
    """Grupo D: pasajes controlados de obras distintas; no citas verificadas."""
    def test_explicit_aliases_on_other_works_remain_audited(self):
        cases = (
            ('El conde de Montecristo', 'Alexandre Dumas', 'Edmond Dantès',
             'conde de Montecristo'),
            ('El fantasma de la ópera', 'Gaston Leroux', 'Erik', 'Fantasma'),
            ('La vuelta al mundo en ochenta días', 'Jules Verne', 'Jean Passepartout',
             'Picaporte'),
        )
        for title, author, name, alias in cases:
            with self.subTest(title=title):
                # Lowercase titles are not an inferred alias: this fixture
                # provides the explicit spelling as a declared candidate.
                sources = evidence(title, author, [(name,
                    'También conocido como ' + alias + ', es un personaje de esta novela.')])
                sources[1]['character_facts'][0]['aliases'] = [alias]
                request = {'task': 'character', 'focus': 'all', 'title': title,
                           'targets': sources[:1], 'names': [alias], 'ambiguous': False}
                result = answer_from_sources('¿Quién es ' + alias + '?', request, sources)
                self.assertIsNotNone(result)
                self.assertEqual(result.status, 'answered')
                self.assertTrue(result.diagnostics['audit']['claims'])

    def test_shared_alias_is_not_transitively_a_direct_equivalence(self):
        from .literary_memory import _character_entity_keys
        # Three independent chains, reversed rows, and a second work keep
        # canonical links but never cross the shared nickname or work scope.
        rows = []
        for work in ('obra-uno', 'obra-dos'):
            for name, aliases in (('Alba Norte', ['Nora']), ('Beatriz Sur', ['Nora']),
                                  ('Nora', []), ('Clara Este', ['Ceci']), ('Ceci', [])):
                rows.append(({}, {'name': name, 'aliases': aliases}, {'work_id': work}))
        expected = None
        for ordered in (rows, list(reversed(rows))):
            grouped = _character_entity_keys(ordered)
            if expected is None:
                expected = grouped
            self.assertEqual(grouped, expected)
            for work in ('obra-uno', 'obra-dos'):
                self.assertEqual(len({grouped[(work, label)] for label in
                    ('alba norte', 'beatriz sur', 'nora')}), 3)
                self.assertEqual(grouped[(work, 'clara este')], grouped[(work, 'ceci')])
            self.assertNotEqual(grouped[('obra-uno', 'ceci')], grouped[('obra-dos', 'ceci')])
