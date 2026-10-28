"""Idempotency, honest update counts and evidence/metadata coverage."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from .literary_acquisition import _connect, _put
from .literary_gutenberg import catalog_record
from .literary_memory import coverage_snapshot, remember_evidence


class AcquisitionReportingTests(SimpleTestCase):
    def test_new_catalogue_snapshot_reports_update_not_new_insertion(self):
        import gzip
        from .literary_gutenberg import import_catalog
        from .test_literary_gutenberg import GutenbergCatalogTests
        with TemporaryDirectory() as folder:
            root = Path(folder)
            first = GutenbergCatalogTests().catalog(root / 'v1.csv.gz', count=1)
            second = root / 'v2.csv.gz'
            second.write_bytes(gzip.compress(gzip.decompress(first.read_bytes()).replace(b'History', b'Philosophy')))
            args = {'state_database': root / 'ledger.sqlite3', 'memory_database': root / 'memory.sqlite3'}
            self.assertEqual(import_catalog(first, **args)['inserted'], 1)
            report = import_catalog(second, **args)
            self.assertEqual(report['updated'], 1)
            self.assertEqual(report['inserted'], 0)
            self.assertEqual(coverage_snapshot(args['memory_database'])['works_catalogued'], 1)

    def record(self):
        return catalog_record({'Text#': '840001', 'Title': 'Catálogo de prueba',
                               'Authors': 'Prueba, Autora', 'Language': 'es'})

    def test_inserts_updates_duplicates_and_old_revisions_are_distinct(self):
        with TemporaryDirectory() as folder, closing(_connect(Path(folder) / 'ledger.sqlite3', write=True)) as db:
            record = self.record()
            with db:
                self.assertEqual(_put(db, record, with_status=True), 'inserted')
                self.assertEqual(_put(db, record, with_status=True), 'duplicates')
                record.update(revision=2, title='Título corregido')
                self.assertEqual(_put(db, record, with_status=True), 'updated')
                record.update(revision=1, title='No degradar')
                self.assertEqual(_put(db, record, with_status=True), 'stale')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM acquisition_records').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM acquisition_history').fetchone()[0], 1)

    def test_catalogue_metadata_does_not_claim_summary_characters_or_text(self):
        record = self.record()
        with TemporaryDirectory() as folder:
            database = Path(folder) / 'memory.sqlite3'
            self.assertEqual(coverage_snapshot(database)['works_catalogued'], 0)
            self.assertFalse(database.exists())
            for _ in range(2):
                remember_evidence([record['book']], record['sources'], database=database)
            counts = coverage_snapshot(database)
            self.assertEqual(counts['works_catalogued'], 1)
            self.assertEqual(counts['authors'], 1)
            self.assertEqual(counts['current_sources'], 1)
            self.assertEqual(counts['works_with_admitted_descriptions'], 0)
            self.assertEqual(counts['works_with_characters'], 0)
            self.assertEqual(counts['works_with_narrative_facts'], 0)
