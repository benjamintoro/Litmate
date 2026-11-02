"""Fixtures sintéticas, SQLite aislado y el importador existente; sin red."""
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
from django.test import TestCase, override_settings
from .knowledge_models import KBRecord, KBName, KBRelation, KBVersion, KBProjection
from .bibliographic_repository import project_ledger, lookup_sources, put_metadata, metadata_record
from .literary_acquisition import import_openlibrary_dump, _connect, _put
from .test_literary_acquisition import corpus, ol_line


@override_settings(LITMATE_STRUCTURED_KNOWLEDGE=True)
class BibliographicRepositoryTests(TestCase):
    def test_narrative_references_use_admitted_catalogue_urls_when_preferred_identity_changes(self):
        from .continuous_knowledge import project_references
        from .literary_identity import stable_work_id
        self.project()
        record = KBRecord.objects.filter(kind='work').first()
        book = lookup_sources(record.label)[0]
        book = {**book,
                'url':record.source_url,'memory_verified':True}
        wid = stable_work_id(book['title'],book['author'])
        preferred = {**book,'url':'https://www.wikidata.org/wiki/Q123','work_id':wid}
        narrative = {'kind':'web','title':book['title'],'author':'Fuente web',
                     'work_title':book['title'],'work_author':book['author'],'work_binding_verified':True,
                     'memory_source_id':'a'*64,'memory_verified':True}
        with patch('core.literary_memory.get_work',return_value=preferred), \
                patch('core.literary_memory.retrieve_evidence',return_value=([book],[book,narrative])):
            self.assertEqual(project_references([wid]),1)
            self.assertEqual(project_references([wid]),0)
        self.assertTrue(KBRelation.objects.filter(record=record,predicate='memory_evidence').exists())

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.ledger, self.memory = root/'ledger.sqlite3', root/'memory.sqlite3'
        self.dump = root/'official.tsv'
        self.dump.write_bytes(b''.join(corpus()))
        import_openlibrary_dump(self.dump, state_database=self.ledger, memory_database=self.memory,
            source_url='https://openlibrary.org/data/ol_dump_works_2026-10-01.txt.gz')

    def project(self, **kwargs):
        return project_ledger(self.ledger, **kwargs)

    def raw(self, key):
        db = _connect(self.ledger)
        try:
            return json.loads(db.execute('SELECT record FROM acquisition_records WHERE external_id=?', (key,)).fetchone()[0])
        finally:
            db.close()

    def test_work_edition_author_identifiers_rights_and_provenance(self):
        report = self.project()
        self.assertEqual(report['inserted'], 3)
        self.assertEqual(set(KBRecord.objects.values_list('kind',flat=True)), {'work','edition','author'})
        self.assertEqual(KBRelation.objects.filter(predicate='edition_of').count(), 1)
        self.assertEqual(KBRelation.objects.filter(predicate='isbn').count(), 2)
        self.assertFalse(KBRecord.objects.exclude(verified_at=None).exists())
        serialized = json.dumps(list(KBRecord.objects.values_list('payload',flat=True)))
        self.assertNotIn('SINOPSIS NO AUTORIZADA', serialized)
        self.assertNotIn('BIOGRAF', serialized)
        self.assertIn('dataset_sha256', serialized)
        sources = lookup_sources('Novela de prueba')
        self.assertTrue(sources)
        self.assertEqual(sources[0]['author'], 'Autora de prueba')
        self.assertEqual(sources[0]['description'], '')

    def test_resume_and_replay_are_idempotent(self):
        first = self.project(max_records=2, batch_size=1)
        self.assertEqual(first['inserted'], 2)
        second = self.project(batch_size=1)
        self.assertEqual(second['inserted'], 1)
        replay = self.project(replay=True)
        self.assertEqual(replay['duplicates'], 3)
        self.assertEqual(KBRecord.objects.count(), 3)
        self.assertEqual(KBVersion.objects.count(), 3)

    def test_failed_batch_rolls_back_records_and_checkpoint(self):
        def interrupt(_):
            raise RuntimeError('simulated process interruption')
        with self.assertRaises(RuntimeError):
            self.project(batch_size=2, after_record=interrupt)
        self.assertEqual(KBRecord.objects.count(), 0)
        self.assertEqual(self.project()['inserted'], 3)

    def test_corrupt_record_does_not_contaminate_valid_records(self):
        db = _connect(self.ledger, write=True)
        with db:
            db.execute("UPDATE acquisition_records SET record='malformed' WHERE kind='edition'")
        db.close()
        report = self.project()
        self.assertEqual(report['rejected'], 1)
        self.assertEqual(report['inserted'], 2)

    def test_staged_unverified_dump_is_not_exposed(self):
        db = _connect(self.ledger, write=True)
        with db:
            db.execute("UPDATE acquisition_outbox SET state='staged'")
        db.close()
        self.assertTrue(self.project().get('blocked_on_unverified_source'))
        self.assertEqual(KBRecord.objects.count(), 0)

    def test_incremental_updates_get_a_new_cursor_and_preserve_versions(self):
        self.project()
        revised = self.dump.with_name('official_v2.tsv')
        lines = corpus()
        lines[1] = ol_line('work', '/works/OL2W', title='Novela de prueba revisada', revision=2,
                          authors=[{'author': {'key': '/authors/OL1A'}}])
        revised.write_bytes(b''.join(lines))
        import_openlibrary_dump(revised, state_database=self.ledger, memory_database=self.memory,
            source_url='https://openlibrary.org/data/ol_dump_works_2026-10-02.txt.gz')
        self.assertEqual(self.project()['updated'], 1)
        self.assertEqual(KBRecord.objects.count(), 3)
        self.assertEqual(KBVersion.objects.filter(record__kind='work').count(), 2)

    def test_conflicting_same_revision_is_quarantined(self):
        self.project()
        record = self.raw('/works/OL2W')
        record['title'] = 'Otra identidad contradictoria'
        self.assertEqual(put_metadata(record, time.time()), 'conflicts')
        self.assertEqual(KBRecord.objects.filter(status='conflict').count(), 1)
        self.assertEqual(lookup_sources('Novela de prueba'), [])  # No authors from a conflicted work.
        put_metadata(self.raw('/works/OL2W'), time.time())
        self.assertEqual(KBRecord.objects.filter(status='conflict').count(), 1)

    def test_homonyms_are_not_merged_by_title_or_author_alias(self):
        self.project()
        record = self.raw('/works/OL2W')
        record.update(url='https://openlibrary.org/works/OL99W', external_id='/works/OL99W', author_keys=[])
        put_metadata(record, time.time())
        author = self.raw('/authors/OL1A')
        author.update(url='https://openlibrary.org/authors/OL99A', external_id='/authors/OL99A')
        put_metadata(author, time.time())
        self.assertEqual(KBRecord.objects.filter(kind='author').count(), 2)
        self.assertEqual(KBRecord.objects.filter(kind='work').count(), 2)
        self.assertEqual(KBName.objects.filter(normalized='autora de prueba',current=True).count(), 2)

    def test_memory_limits_and_missing_evidence_do_not_invent_plot(self):
        self.assertTrue(self.project(max_storage_mb=1)['inserted'])
        from .ai_quick_answers import catalogue_lookup_answer
        self.assertIsNone(catalogue_lookup_answer('De qué trata Novela de prueba', [], lookup_sources))
        answer = catalogue_lookup_answer('¿Quién escribió Novela de prueba?', [], lookup_sources)
        self.assertIsNotNone(answer)
        self.assertIn('Autora de prueba', answer.text)

    def test_generated_or_private_record_cannot_be_admitted(self):
        record = self.raw('/works/OL2W')
        record['generated_by'] = 'Qwen'
        with self.assertRaises(ValueError):
            metadata_record(record)

    def test_provenance_cannot_publish_private_fields(self):
        record = self.raw('/works/OL2W')
        record['provenance']['private_conversation'] = 'private text not allowed'
        self.assertNotIn('private text', json.dumps(metadata_record(record)))

    def test_new_metadata_does_not_replace_bundled_narrative(self):
        record = self.raw('/works/OL2W')
        record.update(title='El principito')
        author = self.raw('/authors/OL1A')
        author['name'] = 'Antoine de Saint-Exupéry'
        put_metadata(author, time.time())
        put_metadata(record, time.time())
        from .ai_quick_answers import quick_knowledge_sources
        sources = quick_knowledge_sources('El principito')
        self.assertTrue(any(source.get('description') and 'rosa' in source['description'] for source in sources))

    def test_original_row_integrity_uses_scalar_primary_key(self):
        import gzip
        from .models import Autor
        from django.db import connection
        from .database_transfer import inspect_table, table_rows, fingerprint, encode
        from .bibliographic_operations import preserve_existing_rows
        Autor.objects.create(nombre='Autora original')
        root = Path(self.directory.name)/'snapshot'
        folder = root/'database'
        folder.mkdir(parents=True)
        columns, pk, _ = inspect_table(connection, 'core_autor')
        rows = table_rows(connection, 'core_autor')
        with gzip.open(folder/'core_autor.jsonl.gz', 'wt', encoding='utf-8') as stream:
            for row in rows:
                stream.write(json.dumps([encode(value) for value in row])+'\n')
        metadata = {'tables': {'core_autor': {**fingerprint('core_autor',columns,rows,pk),
            'columns': columns, 'pk': pk, 'file': 'core_autor.jsonl.gz'}}}
        result = preserve_existing_rows(root, {'database': metadata})
        self.assertTrue(result['core_autor']['unchanged'])

    def test_admitted_gutenberg_metadata_can_answer_authorship_without_plot(self):
        from .literary_gutenberg import catalog_record
        from .ai_quick_answers import catalogue_lookup_answer
        raw = catalog_record({'Text#': '999999', 'Title': 'Cuaderno del horizonte',
            'Authors': 'Prueba, Ada, 1800-1880', 'Language': 'es', 'Type': 'Text'})
        put_metadata(raw, time.time())
        sources = lookup_sources('Cuaderno del horizonte')
        self.assertEqual(sources[0]['edition_id'], '999999')
        answer = catalogue_lookup_answer('¿Quién escribió Cuaderno del horizonte?', [], lookup_sources)
        self.assertIsNotNone(answer)
        self.assertIsNone(catalogue_lookup_answer('De qué trata Cuaderno del horizonte', [], lookup_sources))
        sources[0]['description'] = 'Cuaderno del horizonte, de Ada Prueba. Temas del catálogo: Historia y literatura.'
        self.assertIsNone(catalogue_lookup_answer('De qué trata Cuaderno del horizonte', [], lambda q: sources))

    def test_metadata_source_allowlist_rejects_spoofed_hosts_or_rights(self):
        from .ai_catalog_fallback import _topic_catalogue_origin
        source = {'kind': 'book', 'source': 'Project Gutenberg', 'title': 'Cuaderno del horizonte',
            'author': 'Ada Prueba', 'url': 'https://www.gutenberg.org/ebooks/999999',
            'policy': 'gutenberg-catalog-public-domain-v1', 'license': 'CC0-1.0'}
        self.assertTrue(_topic_catalogue_origin(source))
        for change in ({'url': 'https://www.gutenberg.org.evil.invalid/ebooks/999999'},
                       {'policy': 'unknown'}, {'license': 'all-rights-reserved'}, {'kind': 'web'}):
            self.assertFalse(_topic_catalogue_origin({**source, **change}))

    def test_older_catalog_does_not_replace_current_observation(self):
        self.project()
        record = self.raw('/works/OL2W')
        before = KBRecord.objects.get(kind='work').retrieved_at
        self.assertEqual(put_metadata(record, time.time()-3600), 'stale')
        self.assertEqual(KBRecord.objects.get(kind='work').retrieved_at, before)

    def test_ambiguous_result_limit_does_not_hide_other_candidates(self):
        self.project()
        for index in range(10):
            record = self.raw('/works/OL2W')
            record['url'] = f'https://openlibrary.org/works/OL{10000+index}W'
            put_metadata(record, time.time())
        self.assertEqual(lookup_sources('Novela de prueba', maximum=4), [])

    def test_configured_storage_limit_stops_before_unbounded_growth(self):
        path = self.dump.with_name('large.tsv')
        lines = [ol_line('author', f'/authors/OL{50000+i}A', name=f'Autora {i}',
                alternate_names=[f'Alias {i} {j} '+('z'*180) for j in range(24)]) for i in range(100)]
        path.write_bytes(b''.join(lines))
        import_openlibrary_dump(path, state_database=self.ledger, memory_database=self.memory,
            source_url='https://openlibrary.org/data/ol_dump_authors_2026-10-01.txt.gz')
        report = self.project(max_storage_mb=1, max_records=100, batch_size=10)
        self.assertTrue(report.get('storage_limit'))
        self.assertLess(KBRecord.objects.count(), 100)

    def test_correction_requires_operator_and_records_primary_source_review(self):
        from .bibliographic_repository import review_version
        self.project()
        record = KBRecord.objects.get(kind='work')
        version = record.versions.first()
        with self.assertRaises(ValueError):
            review_version(record.id, version.id, evidence_url=record.source_url)
        with self.assertRaises(ValueError):
            review_version(record.id, version.id, evidence_url='https://example.org/', operator_confirmed=True)
        audit = review_version(record.id, version.id, evidence_url=record.source_url, operator_confirmed=True)
        record.refresh_from_db()
        self.assertIsNotNone(record.verified_at)
        self.assertEqual(audit['selected_version'], version.id)
        self.assertEqual(record.versions.count(), 2)
        updated = self.raw('/works/OL2W')
        updated.update(title='Otro dato nuevo', revision=2)
        self.assertEqual(put_metadata(updated, time.time()), 'conflicts')

    def test_literal_book_title_is_not_interpreted_as_a_greeting(self):
        self.project()
        for index, title in enumerate(('Hola, horizonte', 'Hola', 'Yo')):
            record = self.raw('/works/OL2W')
            record.update(url=f'https://openlibrary.org/works/OL{88000+index}W', title=title)
            put_metadata(record, time.time())
            self.assertEqual(lookup_sources(title)[0]['title'], title)

    def test_different_languages_keep_separate_editions(self):
        self.project()
        record = self.raw('/books/OL3M')
        record.update(url='https://openlibrary.org/books/OL88M', title='Un horizonte en francés',
                      languages=['fra'], isbns=[])
        put_metadata(record, time.time())
        original = lookup_sources('Novela de prueba, edición')[0]
        translation = lookup_sources('Un horizonte en francés')[0]
        self.assertEqual(original['language'], 'spa')
        self.assertEqual(translation['language'], 'fra')
        self.assertNotEqual(original['book_id'], translation['book_id'])
