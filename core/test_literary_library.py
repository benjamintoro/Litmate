"""Corpus de prueba sintético, sin red, textos protegidos ni base de producción."""
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch
import zipfile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from .literary_library import (chapter_chunks, download_original, export_rag,
    extract_chapters, import_manifest, library_status, read_gutenberg_rdf,
    retract_document, retrieve_library, validate_record, list_library_books)


class LiteraryLibraryTests(SimpleTestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / 'library.sqlite3'
        self.storage = self.root / 'stored'
        self.raw = ('CAPÍTULO I\n\nAlicia cuida una rosa azul en un jardín. Su amiga Elena '
                    'viaja hasta la casa para conocer el jardín.\n\nCAPÍTULO II\n\nElena y Alicia '
                    'conversan junto a la ventana sobre la rosa y el regreso al pueblo.').encode()
        (self.root / 'original.txt').write_bytes(self.raw)
        self.item = {'title': 'El jardín de prueba', 'author': 'Autora de prueba', 'language': 'es',
            'edition': 'Edición sintética de pruebas', 'source_url': 'https://example.org/original',
            'path': 'original.txt', 'sha256': hashlib.sha256(self.raw).hexdigest(),
            'rights': {'status': 'open_license', 'license': 'CC0-1.0', 'jurisdiction': 'CL',
                'edition_covered': True, 'statement': 'Texto sintético original creado para estas pruebas automatizadas.',
                'reviewed_at': datetime.now(timezone.utc).date().isoformat(),
                'evidence_urls': ['https://creativecommons.org/publicdomain/zero/1.0/']}}
        self.manifest = self.root / 'manifest.json'
        self._manifest()

    def _manifest(self, items=None):
        self.manifest.write_text(json.dumps({'version': 1, 'books': items or [self.item]}), encoding='utf-8')

    def _import(self, **kwargs):
        return import_manifest(self.manifest, self.database, self.storage, **kwargs)

    def test_dry_run_validates_and_writes_nothing(self):
        before = set(self.root.iterdir())
        report = self._import(dry_run=True)
        self.assertEqual(report['imported'], 1)
        self.assertEqual(report['errors'], [])
        self.assertEqual(set(self.root.iterdir()), before)

    def test_import_real_index_retrieves_exact_evidence_and_chapter(self):
        report = self._import()
        self.assertEqual(report['imported'], 1)
        self.assertEqual(report['errors'], [])
        sources = retrieve_library('Alicia rosa', self.database,
            books=[{'title': self.item['title'], 'author': self.item['author']}])
        self.assertTrue(sources)
        self.assertEqual(sources[0]['title'], self.item['title'])
        self.assertIn('capítulo/sección', sources[0]['locator'])
        self.assertIn(sources[0]['description'], self.raw.decode())
        self.assertEqual(sources[0]['original_sha256'], self.item['sha256'])
        self.assertEqual(sources[0]['url'], self.item['source_url'])
        self.assertTrue(sources[0]['indexing_authorized'])

    def test_original_intact_and_resume_deduplicates(self):
        self._import()
        self.assertEqual((self.storage / 'originals' / (self.item['sha256'] + '.txt')).read_bytes(), self.raw)
        report = self._import()
        self.assertEqual((report['imported'], report['skipped']), (0, 1))
        self.assertEqual(library_status(self.database)['active'], 1)

    def test_identity_filter_does_not_mix_other_author(self):
        self._import()
        self.assertEqual(retrieve_library('rosa', self.database,
            books=[{'title': self.item['title'], 'author': 'Otro autor'}]), [])

    def test_hash_mismatch_not_persisted(self):
        self.item['sha256'] = '0' * 64
        self._manifest()
        report = self._import()
        self.assertIn('SHA256', report['errors'][0]['error'])
        self.assertFalse(self.database.exists())

    def test_gutenberg_us_status_does_not_authorize_chile(self):
        item = deepcopy(self.item)
        item['rights']['status'] = 'public_domain_us'
        with self.assertRaises(ValueError):
            validate_record(item)
        item['rights']['status'] = 'public_domain'
        with self.assertRaises(ValueError):
            validate_record(item)

    def test_public_domain_requires_all_edition_creators(self):
        item = deepcopy(self.item)
        item['rights'].update(status='public_domain', creators=[{'name': self.item['author'],
            'death_year': 1900, 'evidence_url': 'https://example.org/authority'}])
        self.assertIn('Public domain', validate_record(item)['license'])
        item['rights']['creators'].append({'name': 'Traductor', 'death_year': 2001,
                                         'evidence_url': 'https://example.org/translator'})
        with self.assertRaises(ValueError):
            validate_record(item)

    def test_unknown_license_edition_and_jurisdiction_rejected(self):
        for key, value in [('license', 'Any license'), ('edition_covered', False), ('jurisdiction', 'US')]:
            item = deepcopy(self.item)
            item['rights'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_record(item)

    def test_path_cannot_escape_manifest_or_use_symlink(self):
        self.item['path'] = '../original.txt'
        self._manifest()
        self.assertIn('relativo', self._import()['errors'][0]['error'])

    def test_storage_and_pause_limits(self):
        report = self._import(max_total_bytes=10)
        self.assertEqual(report['stopped'], 'storage_limit')
        self.assertFalse(self.database.exists())
        report = self._import(stop=lambda: True)
        self.assertEqual(report['stopped'], 'paused')
        self.assertFalse(self.database.exists())

    def test_repeated_small_batches_advance_past_already_imported_items(self):
        other = deepcopy(self.item)
        other['title'] = 'Otra obra de prueba'
        self._manifest([self.item, other])
        first = self._import(max_books=1)
        self.assertEqual((first['imported'], first['stopped']), (1, 'book_limit'))
        second = self._import(max_books=1)
        self.assertEqual((second['imported'], second['skipped']), (1, 1))
        self.assertEqual(library_status(self.database)['active'], 2)

    def test_status_readonly_does_not_create_database(self):
        self.assertFalse(library_status(self.database)['exists'])
        self.assertFalse(self.database.exists())

    def test_retract_removes_index_only_and_resume_does_not_reactivate(self):
        self._import()
        document = validate_record(self.item)['document_id']
        self.assertTrue(retract_document(document, self.database, reason='Permiso retirado'))
        self.assertEqual(retrieve_library('rosa', self.database), [])
        status = library_status(self.database)
        self.assertEqual((status['active'], status['retracted']), (0, 1))
        self.assertGreater(status['chapters'], 0)
        self.assertTrue((self.storage / 'originals' / (self.item['sha256'] + '.txt')).exists())
        self.assertEqual(self._import()['skipped'], 1)

    def test_derived_export_does_not_touch_user_folder(self):
        self._import()
        folder = self.root / 'user'
        folder.mkdir()
        (folder / 'personal.txt').write_text('Privado')
        with self.assertRaises(ValueError):
            export_rag(self.database, folder)
        export = self.root / 'export'
        result = export_rag(self.database, export)
        self.assertEqual(len(result), 1)
        self.assertTrue((export / 'metadatos.json').is_file())

    def test_exported_index_rehydrates_provenance_and_rejects_retracted_document(self):
        from .local_rag import index_documents
        self._import()
        export, index = self.root / 'export', self.root / 'derived.sqlite3'
        metadata = export_rag(self.database, export)
        index_documents(export, index, metadata=metadata)
        sources = retrieve_library('Alicia rosa', self.database, index=index)
        self.assertTrue(sources)
        self.assertEqual(sources[0]['author'], self.item['author'])
        self.assertEqual(sources[0]['original_sha256'], self.item['sha256'])
        self.assertIn('capítulo/sección', sources[0]['locator'])
        retract_document(validate_record(self.item)['document_id'], self.database, reason='Corrección')
        self.assertEqual(retrieve_library('Alicia rosa', self.database, index=index), [])
        export_rag(self.database, export)
        self.assertEqual(list(export.glob('*.txt')), [])

    def test_export_does_not_overwrite_modified_derived_file(self):
        self._import()
        folder = self.root / 'export'
        metadata = export_rag(self.database, folder)
        path = folder / next(iter(metadata))
        path.write_text('Mis notas personales', encoding='utf-8')
        with self.assertRaises(ValueError):
            export_rag(self.database, folder)
        self.assertEqual(path.read_text(encoding='utf-8'), 'Mis notas personales')

    def test_import_rejects_embedded_identity_mismatch(self):
        raw = b'Title: Another work\nAuthor: Somebody else\n\n' + self.raw
        (self.root / 'original.txt').write_bytes(raw)
        self.item['sha256'] = hashlib.sha256(raw).hexdigest()
        self._manifest()
        self.assertIn('título interno', self._import()['errors'][0]['error'])
        self.assertFalse(self.database.exists())

    def test_false_declared_language_does_not_silently_persist(self):
        raw = ('The garden was the place that she was in, and the girl was with her '
               'friend and the house was the place that they were from. ' * 20).encode()
        (self.root / 'original.txt').write_bytes(raw)
        self.item['sha256'] = hashlib.sha256(raw).hexdigest()
        self._manifest()
        self.assertIn('lingüística', self._import()['errors'][0]['error'])

    def test_arbitrary_sqlite_is_never_adopted_or_modified(self):
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('CREATE TABLE personal_notes(value TEXT)')
            db.execute('INSERT INTO personal_notes VALUES ("private")')
        original = self.database.read_bytes()
        with self.assertRaises(ValueError):
            self._import()
        self.assertEqual(self.database.read_bytes(), original)
        with self.assertRaises(ValueError):
            library_status(self.database)
        self.assertEqual(self.database.read_bytes(), original)

    def test_direct_library_api_rejects_other_application_database(self):
        from django.conf import settings
        with self.assertRaises(ValueError):
            import_manifest(self.manifest, settings.LITMATE_RAG_DB, self.storage)

    def test_original_copyright_notice_conflicts_with_public_domain_claim(self):
        raw = b'Copyrighted. All rights reserved.\n' + self.raw
        (self.root / 'original.txt').write_bytes(raw)
        self.item['sha256'] = hashlib.sha256(raw).hexdigest()
        self.item['rights'].update(status='public_domain', creators=[{'name': self.item['author'],
            'death_year': 1900, 'evidence_url': 'https://example.org/authority'}])
        self._manifest()
        self.assertIn('contradice', self._import()['errors'][0]['error'])
        self.assertFalse(self.database.exists())

    def test_expired_titlepage_notice_does_not_look_like_current_copyright(self):
        raw = b'Copyright, 1897, by Autora de prueba. All rights reserved.\n\n' + self.raw
        (self.root / 'original.txt').write_bytes(raw)
        self.item['sha256'] = hashlib.sha256(raw).hexdigest()
        self.item['rights'].update(status='public_domain', creators=[{'name': self.item['author'],
            'death_year': 1912, 'evidence_url': 'https://example.org/authority'}])
        self._manifest()
        self.assertEqual(self._import()['imported'], 1)

    def test_current_rights_reserved_notice_still_rejects_public_domain_claim(self):
        year = datetime.now(timezone.utc).year
        raw = (f'Copyright, {year}, new edition. All rights reserved.\n\n').encode() + self.raw
        (self.root / 'original.txt').write_bytes(raw)
        self.item['sha256'] = hashlib.sha256(raw).hexdigest()
        self.item['rights'].update(status='public_domain', creators=[{'name': self.item['author'],
            'death_year': 1912, 'evidence_url': 'https://example.org/authority'}])
        self._manifest()
        self.assertIn('contradice', self._import()['errors'][0]['error'])

    def test_gutenberg_marker_separates_titlepage_from_current_metadata(self):
        raw = (b'*** START OF THE PROJECT GUTENBERG EBOOK TEST ***\n\n'
            b'Copyright, 1897, by Autora de prueba. All rights reserved.\n\n') + self.raw
        (self.root / 'original.txt').write_bytes(raw)
        self.item['sha256'] = hashlib.sha256(raw).hexdigest()
        self.item['rights'].update(status='public_domain', creators=[{'name': self.item['author'],
            'death_year': 1912, 'evidence_url': 'https://example.org/authority'}])
        self._manifest()
        self.assertEqual(self._import()['imported'], 1)

    def test_bce_creator_death_year_valid_but_year_zero_is_not(self):
        item = deepcopy(self.item)
        item['author'] = 'Plato'
        item['rights'].update(status='public_domain', creators=[{'name': 'Plato',
            'death_year': -348, 'evidence_url': 'https://example.org/plato'},
            {'name': 'Benjamin Jowett', 'death_year': 1893, 'evidence_url': 'https://example.org/jowett'}])
        self.assertIn('Public domain', validate_record(item)['license'])
        item['rights']['creators'][0]['death_year'] = 0
        with self.assertRaises(ValueError):
            validate_record(item)

    def test_catalog_lookup_returns_identity_and_only_documented_aliases(self):
        self.item['confirmed_aliases'] = [{'title': 'El jardín azul',
            'source_url': 'https://openlibrary.org/works/OL1W',
            'evidence': 'El jardín de prueba también se titula El jardín azul.'},
            {'title': 'Obra no demostrada', 'source_url': 'https://openlibrary.org/works/OL1W',
             'evidence': 'Una coincidencia sin ambos títulos.'}]
        self._manifest()
        self._import()
        books = list_library_books('Dime la trama de El jardín azul', self.database)
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]['title'], self.item['title'])
        self.assertEqual([a['title'] for a in books[0]['confirmed_aliases']], ['El jardín azul'])
        self.assertEqual(list_library_books('Otra obra', self.database), [])

    def test_gutenberg_header_footer_removed_only_from_derived_text(self):
        raw = (b'License header\n*** START OF THE PROJECT GUTENBERG EBOOK TEST ***\n'
            + self.raw + b'\n*** END OF THE PROJECT GUTENBERG EBOOK TEST ***\nLicense footer')
        chapters = extract_chapters(raw, 'txt')
        self.assertNotIn('License', ' '.join(body for _, body in chapters))

    def test_chunks_do_not_cut_normal_paragraphs_or_cross_chapters(self):
        body = ('Primero hay un párrafo completo. ' * 10).strip() + '\n\n' + ('Segundo párrafo. ' * 40).strip()
        chunks = list(chapter_chunks(body, maximum=500))
        for offset, chunk in chunks:
            self.assertEqual(body[offset:offset + len(chunk)], chunk)
        self.assertEqual(chunks[0][1], body.split('\n\n')[0])

    def _epub(self, chapter=None, extra=None):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('mimetype', 'application/epub+zip')
            archive.writestr('META-INF/container.xml', '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
            archive.writestr('OPS/book.opf', '<package><manifest><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="a"/></spine></package>')
            archive.writestr('OPS/a.xhtml', chapter or '<html><body><h1>Capítulo primero</h1><p>' + self.raw.decode() + '</p><script>bad()</script></body></html>')
            if extra:
                archive.writestr(*extra)
        return output.getvalue()

    def test_epub_spine_order_and_no_scripts(self):
        chapters = extract_chapters(self._epub(), 'epub')
        self.assertEqual(chapters[0][0], 'Capítulo primero')
        self.assertNotIn('bad()', chapters[0][1])

    def test_epub_zip_slip_rejected_without_extraction(self):
        with self.assertRaises(ValueError):
            extract_chapters(self._epub(extra=('../escape', 'bad')), 'epub')

    def test_rdf_discovery_is_not_full_text_permission(self):
        path = self.root / 'catalog.rdf'
        path.write_text('<rdf xmlns:pg="http://www.gutenberg.org/2009/pgterms/" '
            'xmlns:d="http://purl.org/dc/terms/" xmlns:r="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            '<pg:ebook r:about="ebooks/1"><d:title>Obra</d:title><d:language><r:value>es</r:value></d:language>'
            '<d:rights>Public domain in the USA.</d:rights></pg:ebook></rdf>', encoding='utf-8')
        rows = list(read_gutenberg_rdf(path))
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]['full_text_authorized'])
        self.assertIn('USA', rows[0]['catalog_rights'][0])

    def test_rdf_xml_entities_rejected(self):
        path = self.root / 'bad.rdf'
        path.write_text('<!DOCTYPE rdf [<!ENTITY x "boom">]><rdf/>')
        with self.assertRaises(ValueError):
            list(read_gutenberg_rdf(path))

    def test_utf16_rdf_cannot_hide_entity_declarations(self):
        path = self.root / 'bad-utf16.rdf'
        path.write_bytes('<!DOCTYPE rdf [<!ENTITY x "boom">]><rdf>&x;</rdf>'.encode('utf-16'))
        with self.assertRaises(ValueError):
            list(read_gutenberg_rdf(path))

    def test_utf16_epub_container_cannot_hide_entity_declarations(self):
        raw = io.BytesIO(self._epub())
        output = io.BytesIO()
        with zipfile.ZipFile(raw) as original, zipfile.ZipFile(output, 'w') as archive:
            for name in original.namelist():
                value = original.read(name)
                if name == 'META-INF/container.xml':
                    value = '<!DOCTYPE container [<!ENTITY x "boom">]><container>&x;</container>'.encode('utf-16')
                archive.writestr(name, value)
        with self.assertRaises(ValueError):
            extract_chapters(output.getvalue(), 'epub')

    @patch('core.literary_library._secure_fetch')
    @patch('core.literary_library._robots_permission')
    def test_download_reuses_network_defenses_and_rejects_google(self, robots, fetch):
        fetch.return_value = {'body': b'allowed', 'content_type': 'text/plain'}
        self.assertEqual(download_original('https://gutenberg.pglaf.org/1/1.txt'), b'allowed')
        robots.assert_called_once()
        for url in ['http://localhost/x', 'https://127.0.0.1/x',
                    'https://google.com/search?q=book', 'https://www.gutenberg.org/ebooks/1',
                    'https://www.ibiblio.org/private/file.txt']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                download_original(url)
        self.assertEqual(fetch.call_count, 1)

    def test_command_simulation_and_production_guard(self):
        output = io.StringIO()
        call_command('importar_biblioteca', '--manifiesto', str(self.manifest),
            '--base', str(self.database), '--almacen', str(self.storage), '--simular', stdout=output)
        self.assertTrue(json.loads(output.getvalue())['dry_run'])
        from django.conf import settings
        with self.assertRaises(CommandError):
            call_command('importar_biblioteca', '--base', str(settings.LITMATE_RAG_DB), '--estado')

    def test_index_command_creates_separate_retrievable_index_and_reuses_it(self):
        self._import()
        output, index = io.StringIO(), self.root / 'hybrid.sqlite3'
        export = self.root / 'exported'
        for _ in range(2):
            output.seek(0)
            output.truncate(0)
            call_command('indexar_biblioteca', '--base', str(self.database), '--indice', str(index),
                '--exportar', str(export), stdout=output)
            self.assertEqual(json.loads(output.getvalue())['books'], 1)
        self.assertTrue(retrieve_library('rosa', self.database, index=index))
        self.assertEqual(library_status(self.database)['active'], 1)

    def test_index_command_dry_run_writes_nothing_and_rejects_foreign_target(self):
        self._import()
        output, index = io.StringIO(), self.root / 'hybrid.sqlite3'
        export = self.root / 'exported'
        call_command('indexar_biblioteca', '--base', str(self.database), '--indice', str(index),
            '--exportar', str(export), '--simular', stdout=output)
        self.assertTrue(json.loads(output.getvalue())['dry_run'])
        self.assertFalse(index.exists())
        self.assertFalse(export.exists())
        with self.assertRaises(CommandError):
            call_command('indexar_biblioteca', '--base', str(self.database), '--indice', str(self.database))
        with closing(sqlite3.connect(index)) as db, db:
            db.execute('CREATE TABLE personal_notes(value TEXT)')
        original = index.read_bytes()
        with self.assertRaises(CommandError):
            call_command('indexar_biblioteca', '--base', str(self.database), '--indice', str(index))
        self.assertEqual(index.read_bytes(), original)
