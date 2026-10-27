"""Catálogos simulados: permisos, importación incremental y límites."""
import csv
import gzip
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from .literary_gutenberg import catalog_record, import_catalog, iter_rdf_catalog
from .literary_memory import list_works, retrieve_evidence


class GutenbergCatalogTests(SimpleTestCase):
    def rdf(self, title='Frankenstein', *, about='ebooks/84', extra=''):
        return '''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
          xmlns:dc="http://purl.org/dc/terms/" xmlns:pg="http://www.gutenberg.org/2009/pgterms/">
          <pg:ebook rdf:about="''' + about + '''"><dc:title>''' + title + '''</dc:title>
          <dc:creator><pg:agent><pg:name>Shelley, Mary Wollstonecraft, 1797-1851</pg:name></pg:agent></dc:creator>
          <dc:language><rdf:Description><rdf:value>en</rdf:value></rdf:Description></dc:language>''' + extra + '''
          </pg:ebook></rdf:RDF>'''

    def catalog(self, path, count=3):
        data = io.StringIO()
        writer = csv.DictWriter(data, fieldnames=['Text#', 'Title', 'Authors', 'Language', 'Type', 'Subjects'])
        writer.writeheader()
        for number in range(1, count + 1):
            writer.writerow({'Text#': str(number), 'Title': 'Libro ' + str(number),
                             'Authors': 'Escritor, Autor, 1800-1880', 'Language': 'es',
                             'Type': 'Text', 'Subjects': 'Fiction; History'})
        path.write_bytes(gzip.compress(data.getvalue().encode()))
        return path

    def test_metadata_does_not_copy_generated_summaries_or_grant_text_rights(self):
        record = catalog_record({'Text#': '84', 'Title': 'Frankenstein',
            'Authors': 'Shelley, Mary Wollstonecraft, 1797-1851', 'Language': 'en',
            'Subjects': 'Science fiction', 'summary': 'AI-generated text, not evidence'})
        self.assertEqual(record['book']['author'], 'Mary Wollstonecraft Shelley')
        self.assertEqual(record['book']['description'], '')
        self.assertNotIn('summary', record)
        self.assertNotIn('public_domain', record['book'])

    def test_rejects_ambiguous_creator_roles_and_bad_ids(self):
        row = {'Text#': '1', 'Title': 'Una obra', 'Authors': 'Ana Editora [Editor]', 'Language': 'es'}
        self.assertIsNone(catalog_record(row))
        row.update(Authors='Autora, Ana, 1800-1900', **{'Text#': '../secret'})
        self.assertIsNone(catalog_record(row))

    def test_dry_run_creates_no_ledger_memory_or_parent_directory(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            path = self.catalog(root / 'catalog.csv.gz')
            result = import_catalog(path, state_database=root / 'absent' / 'ledger.sqlite3',
                memory_database=root / 'absent' / 'memory.sqlite3', dry_run=True)
            self.assertEqual(result['accepted'], 3)
            self.assertFalse((root / 'absent').exists())

    def test_checkpoint_resume_and_outbox_project_real_records_once(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            path = self.catalog(root / 'catalog.csv.gz')
            args = {'state_database': root / 'ledger.sqlite3', 'memory_database': root / 'memory.sqlite3'}
            first = import_catalog(path, max_records=2, **args)
            self.assertEqual(first['projection']['projected'], 2)
            second = import_catalog(path, max_records=2, **args)
            self.assertEqual(second['accepted'], 1)
            self.assertEqual(second['offset_before'], 2)
            self.assertEqual(len(list_works(database=args['memory_database'])), 3)
            third = import_catalog(path, **args)
            self.assertEqual(third['accepted'], 0)
            self.assertEqual(third['projection']['projected'], 0)
            books, sources = retrieve_evidence('Libro 1', database=args['memory_database'])
            self.assertTrue(books)
            self.assertTrue(all(source['policy'] == 'gutenberg-catalog-public-domain-v1' for source in sources))
            self.assertFalse(any(source.get('character_facts') for source in sources))

    def test_changed_dump_is_not_silently_resumed(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            path = self.catalog(root / 'catalog.csv.gz')
            args = {'state_database': root / 'ledger.sqlite3', 'memory_database': root / 'memory.sqlite3'}
            import_catalog(path, max_records=1, **args)
            self.catalog(path, count=4)
            with self.assertRaisesMessage(ValueError, 'cambió'):
                import_catalog(path, **args)

    def test_filter_language_and_reject_nonofficial_provenance(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            path = self.catalog(root / 'catalog.csv.gz')
            args = {'state_database': root / 'ledger.sqlite3', 'memory_database': root / 'memory.sqlite3', 'dry_run': True}
            report = import_catalog(path, languages=('en',), **args)
            self.assertEqual(report['accepted'], 0)
            self.assertEqual(report['filtered'], 3)
            with self.assertRaises(ValueError):
                import_catalog(path, source_url='https://localhost/catalog.csv.gz', **args)

    def test_rdf_discovery_extracts_metadata_not_download_permission(self):
        text = '''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
          xmlns:dc="http://purl.org/dc/terms/" xmlns:pg="http://www.gutenberg.org/2009/pgterms/">
          <pg:ebook rdf:about="ebooks/84"><dc:title>Frankenstein</dc:title>
          <dc:creator><pg:agent><pg:name>Shelley, Mary Wollstonecraft, 1797-1851</pg:name></pg:agent></dc:creator>
          <dc:language><rdf:Description><rdf:value>en</rdf:value></rdf:Description></dc:language></pg:ebook></rdf:RDF>'''
        with TemporaryDirectory() as raw:
            path = Path(raw) / 'catalog.rdf'
            path.write_text(text, encoding='utf-8')
            records = list(iter_rdf_catalog(path))
            self.assertEqual(records[0]['book']['title'], 'Frankenstein')
            self.assertNotIn('download_url', records[0])
            path.write_text('<!DOCTYPE x [<!ENTITY y SYSTEM "file:///x">]>' + text, encoding='utf-8')
            with self.assertRaises(ValueError):
                list(iter_rdf_catalog(path))

    def test_untrusted_catalog_bytes_are_not_stored_by_downloader(self):
        from .literary_gutenberg import download_catalog
        with TemporaryDirectory() as raw, patch('core.literary_web._robots_permission'), \
                patch('core.literary_web._secure_fetch', return_value={'body': b'<html>denied</html>'}):
            path = Path(raw) / 'not-created.gz'
            with self.assertRaises(ValueError):
                download_catalog(path)
            self.assertFalse(path.exists())

    def test_rdf_utf16_doctype_cannot_bypass_entity_guard(self):
        payload = '<?xml version="1.0" encoding="UTF-16"?>\n' + (
            '<!DOCTYPE rdf:RDF [<!ENTITY injected "Injected title">]>\n'
        ) + self.rdf('&injected;')
        with TemporaryDirectory() as raw:
            path = Path(raw) / 'hostile.rdf'
            path.write_bytes(payload.encode('utf-16'))
            with self.assertRaises(ValueError):
                list(iter_rdf_catalog(path))

    def test_rdf_rejects_nontext_items_instead_of_labelling_them_books(self):
        payload = self.rdf(extra='''<dc:type><rdf:Description>
            <rdf:value>Sound</rdf:value></rdf:Description></dc:type>''')
        with TemporaryDirectory() as raw:
            path = Path(raw) / 'sound.rdf'
            path.write_text(payload, encoding='utf-8')
            self.assertFalse(any(iter_rdf_catalog(path)))

    def test_invalid_memory_destination_is_rejected_before_creating_ledger(self):
        from django.conf import settings
        with TemporaryDirectory() as raw:
            root = Path(raw)
            path = self.catalog(root / 'catalog.csv.gz')
            ledger = root / 'ledger.sqlite3'
            with self.assertRaises(ValueError):
                import_catalog(path, state_database=ledger,
                    memory_database=settings.LITMATE_AI_RUNTIME_DB, dry_run=True)
            self.assertFalse(ledger.exists())

    def test_gzip_oversized_physical_line_is_rejected_before_csv_allocation(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / 'catalog.csv.gz'
            path.write_bytes(gzip.compress(b'Text#,Title,Authors,Language\n' + b'x' * 64001))
            with self.assertRaises(ValueError):
                import_catalog(path, state_database=root / 'ledger.sqlite3',
                    memory_database=root / 'memory.sqlite3', dry_run=True)

    def test_rdf_limit_is_checked_before_loading_large_document(self):
        with TemporaryDirectory() as raw:
            path = Path(raw) / 'catalog.rdf'
            path.write_text(self.rdf(), encoding='utf-8')
            with self.assertRaises(ValueError):
                list(iter_rdf_catalog(path, maximum_bytes=10))

    def test_rdf_doctype_spanning_reader_blocks_is_still_rejected(self):
        payload = (' ' * (16384 - 5) +
                   '<!DOCTYPE rdf:RDF [<!ENTITY injected "Injected title">]>\n' +
                   self.rdf('&injected;'))
        with TemporaryDirectory() as raw:
            path = Path(raw) / 'boundary.rdf'
            path.write_text(payload, encoding='utf-8')
            with self.assertRaises(ValueError):
                list(iter_rdf_catalog(path))

    def test_invalid_language_filter_does_not_create_state(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            path = self.catalog(root / 'catalog.csv.gz')
            for languages in ('es', ('es', 12), ('english',)):
                with self.subTest(languages=languages), self.assertRaises(ValueError):
                    import_catalog(path, state_database=root / 'absent/ledger.sqlite3',
                        memory_database=root / 'absent/memory.sqlite3', languages=languages,
                        dry_run=True)
            self.assertFalse((root / 'absent').exists())
