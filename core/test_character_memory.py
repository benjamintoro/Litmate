"""Character memory contracts: temporary SQLite, no network or model inference."""
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from . import literary_memory as memory
from .literary_identity import stable_work_id
from .literary_learning import provider_order, run_refresh_batch
from .literary_memory_rag import build_memory_index, search_memory_semantic
from .literary_sources import SearchResults, reserve_page


class CharacterMemoryTests(SimpleTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / 'memory.sqlite3'
        self.index = Path(self.temporary.name) / 'index.sqlite3'
        self.settings_override = override_settings(LITMATE_LITERARY_MEMORY_DB=self.database)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.book = {'title': 'Una aventura verificable', 'author': 'Ana Escritora',
            'kind': 'book', 'source': 'Open Library',
            'url': 'https://openlibrary.org/works/OL123W'}
        self.work_id = stable_work_id(self.book['title'], self.book['author'])

    def page(self, *, book=None, name='Frodo Bolsón', role='Hobbit que lleva el anillo.',
             aliases=None, body=None, language='es', narrative_role=''):
        book = book or self.book
        body = body or name + ': ' + role
        url = 'https://' + language + '.wikipedia.org/wiki/' + book['title'].replace(' ', '_')
        return {'title': book['title'], 'author': 'Fuente web', 'kind': 'web',
            'source': 'Wikipedia', 'url': url, 'description': body,
            'work_title': book['title'], 'work_author': book['author'],
            'work_binding_verified': True, 'license': 'CC-BY-SA-4.0',
            'storage_policy': 'wikipedia-cc-by-sa-4.0-v1',
            'attribution': {'authors': 'Wikipedia contributors', 'title': book['title'],
                'url': url, 'revision_id': '1234',
                'license_url': 'https://creativecommons.org/licenses/by-sa/4.0/'},
            'character_facts': [{'name': name, 'role': role, 'aliases': aliases or [],
                'narrative_role': narrative_role, 'evidence': body}]}

    def remember(self, page, *, book=None):
        book = book or self.book
        return memory.remember_evidence([book], [book, page], database=self.database)

    def retrieve(self, **kwargs):
        return memory.retrieve_character_entities(books=[self.book], database=self.database, **kwargs)

    def test_missing_store_read_does_not_create_database(self):
        self.assertEqual(self.retrieve(names=['Frodo']), [])
        self.assertFalse(self.database.exists())

    def test_explicit_alias_retains_literal_evidence_and_stable_ids(self):
        body = 'Frodo Bolsón, también conocido como Frodo Baggins, es un hobbit que lleva el anillo.'
        page = self.page(body=body, role='hobbit que lleva el anillo', aliases=['Frodo Baggins', 'Sam'])
        self.remember(page)
        revision = memory.revision(self.database)
        entity = self.retrieve(names=['Frodo Baggins'])[0]
        self.assertEqual(entity['canonical_name'], 'Frodo Bolsón')
        self.assertEqual(entity['aliases'], ['Frodo Baggins'])
        self.assertEqual(entity['work_id'], self.work_id)
        self.assertEqual(entity['verification_status'], 'source_supported')
        self.assertFalse(entity['independently_corroborated'])
        evidence = entity['evidence'][0]
        self.assertEqual(evidence['text'], body)
        self.assertEqual(evidence['source']['attribution']['revision_id'], '1234')
        self.assertEqual(len(evidence['supporting_passage_id']), 64)
        self.assertEqual(self.retrieve(names=['Frodo Baggins'])[0], entity)
        self.assertEqual(memory.revision(self.database), revision)
        with closing(sqlite3.connect(self.database)) as db:
            stored = json.loads(db.execute("SELECT record FROM memory_entities WHERE entity_type='character'").fetchone()[0])
        self.assertEqual(stored['aliases'], ['Frodo Baggins'])
        self.assertEqual(stored['verification_status'], 'requires_source_revalidation')

    def test_published_parenthetic_and_mas_conocido_aliases_survive_persistence(self):
        for name, alias, body in (
            ('Bruno', 'Brun', 'Bruno (Brun): Es el ingeniero de la estación.'),
            ('Samsagaz Gamyi', 'Sam', 'Samsagaz Gamyi, más conocido como Sam, es un viajero.'),
        ):
            with self.subTest(alias=alias):
                role = 'Es el ingeniero de la estación.' if alias == 'Brun' else 'viajero'
                self.remember(self.page(name=name, body=body, role=role, aliases=[alias]))
                entity = self.retrieve(names=[alias])[0]
                self.assertEqual(entity['canonical_name'], name)
                self.assertEqual(entity['aliases'], [alias])

    def test_descriptive_parentheses_and_unrelated_classification_are_not_promoted(self):
        page = self.page(body='Frodo Bolsón (Hobbit): Es un viajero.', role='Es un viajero.', aliases=['Hobbit'])
        page['character_facts'][0].update(classification='principal', classification_evidence='Personajes principales')
        page['description'] = '=== Personajes principales ===\nOtro: Es el capitán.\n=== Personajes secundarios ===\n' + page['description']
        self.remember(page)
        entity = self.retrieve()[0]
        self.assertEqual(entity['aliases'], [])
        self.assertEqual(entity['narrative_role'], '')
        self.assertNotIn('classification', entity['evidence'][0]['source']['character_facts'][0])

    def test_cooccurring_names_are_not_aliases(self):
        self.remember(self.page(body='Frodo Bolsón y Sam caminan juntos. Frodo Bolsón es un hobbit.',
            role='hobbit', aliases=['Sam']))
        self.assertEqual(self.retrieve(names=['Sam']), [])
        self.assertEqual(self.retrieve()[0]['aliases'], [])

    def test_explicit_alias_deduplicates_two_source_labels_within_same_work(self):
        self.remember(self.page(body='Frodo Bolsón, también conocido como Frodo Baggins, es un hobbit.',
            role='hobbit', aliases=['Frodo Baggins']))
        self.remember(self.page(name='Frodo Baggins', role='Hobbit viajero.', language='en'))
        entities = self.retrieve()
        self.assertEqual(len(entities), 1)
        self.assertEqual({entities[0]['name'], *entities[0]['aliases']}, {'Frodo Bolsón', 'Frodo Baggins'})
        self.assertEqual(len(entities[0]['evidence']), 2)

    def test_wikidata_membership_does_not_override_an_explanatory_role(self):
        role = 'Personaje registrado para esta obra en Wikidata'
        page = {**self.page(role=role), 'source': 'Wikidata',
            'url': 'https://www.wikidata.org/wiki/Q1234', 'license': 'CC0'}
        self.remember(page)
        self.assertTrue(self.retrieve()[0]['membership_only'])
        self.remember(self.page())
        entity = self.retrieve()[0]
        self.assertFalse(entity['membership_only'])
        self.assertEqual(entity['role'], 'Hobbit que lleva el anillo.')

    def test_another_characters_role_in_separate_sentence_is_rejected(self):
        self.remember(self.page(body='Frodo Bolsón es un hobbit. Gandalf es un mago.', role='mago'))
        self.assertEqual(self.retrieve(), [])

    def test_role_classification_requires_literal_support(self):
        self.remember(self.page(narrative_role='antagonista'))
        self.assertEqual(self.retrieve()[0]['narrative_role'], '')
        self.remember(self.page(body='Frodo Bolsón es el protagonista de la historia.',
            role='protagonista de la historia', narrative_role='protagonista'))
        self.assertEqual(self.retrieve()[0]['narrative_role'], 'protagonista')

    def test_wrong_book_scope_and_ambiguous_unscoped_name_fail_closed(self):
        self.remember(self.page(name='Elena', role='Narradora del viaje.'))
        other = {**self.book, 'title': 'Otra aventura', 'url': 'https://openlibrary.org/works/OL456W'}
        self.remember(self.page(book=other, name='Elena', role='Exploradora de la ciudad.'), book=other)
        self.assertEqual(memory.retrieve_character_entities('Elena', names=['Elena'], database=self.database), [])
        entities = self.retrieve(names=['Elena'])
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]['description'], 'Narradora del viaje.')

    def test_source_expiry_and_replacement_remove_old_entities(self):
        self.remember(self.page())
        entity = self.retrieve()[0]
        expiry = entity['evidence'][0]['source']['expires_at']
        with patch('core.literary_memory.time.time', return_value=expiry + 1):
            self.assertEqual(self.retrieve(), [])
        self.remember(self.page(name='Sam', role='Compañero del viajero.'))
        self.assertEqual(self.retrieve(names=['Frodo Bolsón']), [])
        self.assertEqual(self.retrieve()[0]['name'], 'Sam')

    def test_relationship_evidence_can_come_from_another_current_source(self):
        self.remember(self.page(name='Leo', role='Viajero protagonista.'))
        relation_page = self.page(name='Ada', role='Madre de Leo.', language='en',
            body='Ada es la madre de Leo.', aliases=[])
        relation_page['literary_facts'] = [{'topic': 'relationships', 'subject': 'Leo',
            'relation': 'mother', 'value': 'Ada', 'evidence': relation_page['description']}]
        self.remember(relation_page)
        entity = self.retrieve(names=['Leo'], requirement='relationships')[0]
        self.assertEqual(entity['relations'][0]['value'], 'Ada')
        self.assertEqual(entity['relations'][0]['source_url'], relation_page['url'])
        self.assertEqual(len(entity['relations'][0]['supporting_passage_id']), 64)

    def test_conflicting_relationship_sources_are_not_reused(self):
        for language, parent in [('es', 'Ada'), ('en', 'Bea')]:
            page = self.page(name='Leo', role='Hijo de ' + parent + '.', language=language,
                body='Leo: Hijo de ' + parent + '. Su madre es ' + parent + '.')
            page['literary_facts'] = [{'topic': 'relationships', 'subject': 'Leo',
                'relation': 'mother', 'value': parent, 'evidence': page['description']}]
            self.remember(page)
        self.assertEqual(self.retrieve(), [])

    def test_generated_or_unauthorized_pages_cannot_become_entities(self):
        for extra in ({'llm_generated': True}, {'permanent_index_allowed': False},
                      {'source': 'Modelo local'}, {'license': ''}):
            self.remember({**self.page(), **extra})
        self.assertEqual(self.retrieve(), [])

    def test_specific_requirement_prioritizes_characters_over_newer_metadata(self):
        with patch('core.literary_memory.time.time', return_value=1_000_000):
            self.remember(self.page())
        with patch('core.literary_memory.time.time', return_value=1_000_100):
            memory.remember_evidence([self.book], [self.book], database=self.database)
            _, sources = memory.retrieve_evidence('', books=[self.book], requirement='characters',
                                                  database=self.database, limit=1)
        self.assertEqual(sources[0]['kind'], 'web')
        self.assertEqual(sources[0]['character_facts'][0]['name'], 'Frodo Bolsón')

    def test_semantic_retrieval_filters_work_before_global_ranking(self):
        self.remember(self.page(name='Leo', role='Explorador de una cueva junto al río.'))
        other = {**self.book, 'title': 'Otra aventura', 'url': 'https://openlibrary.org/works/OL456W'}
        self.remember(self.page(book=other, name='Leo', role='Explorador de una cueva junto al río. La cueva es enorme.'), book=other)
        report = build_memory_index(database=self.database, index=self.index)
        self.assertTrue(report['index_updated'])
        books, sources = search_memory_semantic('Leo cueva', books=[self.book],
                                                database=self.database, index=self.index)
        self.assertEqual([book['work_id'] for book in books], [self.work_id])
        self.assertTrue(sources)
        self.assertTrue(all(source['work_id'] == self.work_id for source in sources))
        unknown = {**self.book, 'title': 'Una obra ausente'}
        self.assertEqual(search_memory_semantic('Leo cueva', books=[unknown],
            database=self.database, index=self.index), ([], []))

    def test_short_roles_remain_structured_without_breaking_index_build(self):
        self.remember(self.page(name='Leo', role='Viajero.'))
        report = build_memory_index(database=self.database, index=self.index)
        self.assertTrue(report['index_updated'])
        self.assertEqual(report['short_sources_skipped'], 1)
        self.assertEqual(self.retrieve(names=['Leo'])[0]['role'], 'Viajero.')

    def test_wikipedia_worker_is_opt_in_and_cannot_read_full_pages(self):
        memory.remember_evidence([self.book], [self.book], database=self.database)
        memory.enqueue_refresh(self.work_id, 'characters', 'wikipedia', database=self.database)
        page = self.page(name='Elena', role='Narradora del viaje.',
            body='Elena: Narradora del viaje.\nTomás: Hermano de Elena.')
        page['character_facts'].append({'name': 'Tomás', 'role': 'Hermano de Elena.'})
        def fetch(work, provider):
            self.assertEqual(provider, 'wikipedia')
            self.assertFalse(reserve_page())
            return SearchResults([self.book, page])
        report = run_refresh_batch(database=self.database, max_jobs=1, fetch=fetch)
        self.assertEqual(report['completed'], 1)
        self.assertEqual(report['llm_calls'], 0)
        self.assertEqual(len(self.retrieve()), 2)
        self.assertEqual(provider_order([]), ['openlibrary', 'wikidata'])

    def test_official_wikipedia_intro_is_stored_but_does_not_complete_character_job(self):
        """Real adapter+worker, simulated official JSON; no external HTTP."""
        memory.remember_evidence([self.book], [self.book], database=self.database)
        memory.enqueue_refresh(self.work_id, 'characters', 'wikipedia', database=self.database)
        url = self.page()['url']
        intro = self.book['title'] + ' es una novela de ' + self.book['author'] + '. Narra un viaje por un mundo desconocido.'
        response = {'query': {'pages': {'123': {'pageid': 123, 'title': self.book['title'],
            'extract': intro, 'fullurl': url, 'revisions': [{'revid': 1234}]}}}}
        with patch('core.literary_search._wikipedia_fetch', return_value=response) as fetch, \
                patch('core.literary_search._cached', return_value=None):
            report = run_refresh_batch(database=self.database, max_jobs=1)
        self.assertEqual(fetch.call_count, 1)
        self.assertIn('exintro=1', fetch.call_args.args[0])
        self.assertEqual(report['completed'], 0)
        self.assertEqual(report['deferred'], 1)
        self.assertEqual(report['stored'], 1)
        self.assertEqual(report['jobs'][0]['status'], 'no_evidence')
        self.assertFalse(report['independent_factual_corroboration'])
        _, sources = memory.retrieve_evidence('', books=[self.book], database=self.database)
        wiki = next(source for source in sources if source['source'] == 'Wikipedia')
        self.assertEqual(wiki['description'], intro)
        self.assertEqual(wiki['character_facts'], [])
        self.assertEqual(wiki['attribution']['revision_id'], '1234')
        self.assertEqual(self.retrieve(), [])
        stats = memory.usage_stats(database=self.database)
        self.assertEqual(stats[0]['verified'], 0)

    def test_official_wikipedia_intro_can_complete_metadata_job_with_correct_binding(self):
        memory.remember_evidence([self.book], [self.book], database=self.database)
        memory.enqueue_refresh(self.work_id, 'metadata', 'wikipedia', database=self.database)
        response = {'query': {'pages': {'123': {'pageid': 123, 'title': self.book['title'],
            'extract': self.book['title'] + ', una novela de ' + self.book['author'] + '.',
            'fullurl': self.page()['url'], 'revisions': [{'revid': 5678}]}}}}
        with patch('core.literary_search._wikipedia_fetch', return_value=response), \
                patch('core.literary_search._cached', return_value=None):
            report = run_refresh_batch(database=self.database, max_jobs=1)
        self.assertEqual(report['completed'], 1)
        self.assertEqual(report['stored'], 1)
        self.assertFalse(report['independent_factual_corroboration'])

    def test_wikidata_membership_alone_cannot_complete_character_refresh(self):
        memory.remember_evidence([self.book], [self.book], database=self.database)
        memory.enqueue_refresh(self.work_id, 'characters', 'wikidata', database=self.database)
        role = 'Personaje registrado para esta obra en Wikidata'
        page = {**self.page(body='Frodo Bolsón: ' + role + '\nSam: ' + role, role=role),
            'source': 'Wikidata', 'url': 'https://www.wikidata.org/wiki/Q1234', 'license': 'CC0'}
        page['character_facts'].append({'name': 'Sam', 'role': role})
        report = run_refresh_batch(database=self.database, max_jobs=1,
            fetch=Mock(return_value=SearchResults([page])))
        self.assertEqual(report['completed'], 0)
        self.assertEqual(report['jobs'][0]['status'], 'no_evidence')
        self.assertEqual(memory.usage_stats(database=self.database)[0]['verified'], 0)
        self.assertTrue(all(entity['membership_only'] for entity in self.retrieve()))

    def test_production_character_route_uses_structured_memory_without_network(self):
        from .ai_character_answers import character_answer
        page = self.page(name='Elena', role='Es la protagonista y narradora del viaje.',
            body='Elena: Es la protagonista y narradora del viaje.\nTomás: Es hermano de Elena.')
        page['character_facts'].append({'name': 'Tomás', 'role': 'Es hermano de Elena.'})
        self.remember(page)
        with patch('core.ai_quick_answers.quick_knowledge_sources', return_value=[self.book]), \
                patch('core.literary_memory.retrieve_character_entities', wraps=memory.retrieve_character_entities) as lookup, \
                patch('core.literary_search.search_wikipedia', side_effect=AssertionError('no network')), \
                patch('core.literary_search.search_openlibrary', side_effect=AssertionError('no network')):
            result = character_answer('Dime los personajes de ' + self.book['title'])
        lookup.assert_called_once()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'answered')
        self.assertIn('Elena', result.text)
        self.assertIn('narradora', result.text)
        self.assertTrue(result.diagnostics['verified_character_answer'])

    def test_extractor_main_heading_and_alias_restore_into_production_route_offline(self):
        from .ai_character_answers import character_answer
        from .literary_web import character_content
        extracted = character_content('<h2>Personajes principales</h2><ul>'
            '<li>Ana: Es la capitana de una estación lunar.</li>'
            '<li>Bruno (Brun): Es el ingeniero de la estación lunar.</li></ul>',
            title=self.book['title'])
        page = {**self.page(), 'description': extracted['passage'],
                'character_facts': extracted['character_facts']}
        self.remember(page)
        # Reopen through the production route; no in-memory extractor output
        # or previous conversation is supplied as evidence.
        with patch('core.ai_quick_answers.quick_knowledge_sources', return_value=[self.book]), \
                patch('core.literary_search.search_wikipedia', side_effect=AssertionError('no network')), \
                patch('core.literary_search.search_openlibrary', side_effect=AssertionError('no network')):
            result = character_answer('Dime los personajes principales de ' + self.book['title'])
        self.assertEqual(result.status, 'answered')
        self.assertIn('Ana', result.text)
        self.assertIn('Bruno', result.text)
        entity = self.retrieve(names=['Brun'])[0]
        self.assertEqual(entity['canonical_name'], 'Bruno')
        self.assertEqual(entity['aliases'], ['Brun'])
        self.assertEqual(entity['narrative_role'], 'principal')
        fact = entity['evidence'][0]['source']['character_facts'][1]
        self.assertEqual(fact['classification'], 'principal')
        self.assertEqual(fact['classification_evidence'], 'Personajes principales')

    def test_invalid_argument_types_do_not_trigger_any_retrieval(self):
        self.assertEqual(memory.retrieve_character_entities(names=None, database=self.database), [])
        self.assertEqual(memory.retrieve_character_entities(books='anything', database=self.database), [])
        self.assertEqual(self.retrieve(requirement='exact_passage'), [])
