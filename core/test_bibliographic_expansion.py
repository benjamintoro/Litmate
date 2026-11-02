"""Regresiones con catálogo sintético, sin servicios externos ni datos reales."""
import csv
import gzip
import io
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.test import SimpleTestCase
from .bibliographic_expansion import genre, select_catalog
from .literary_gutenberg import import_catalog
from .literary_acquisition import _connect
from .bibliographic_expansion import preserve_expansion_rows, pending_memory_projection


class ExpansionTests(SimpleTestCase):
    def catalog(self, root, count=12):
        text = io.StringIO()
        writer = csv.DictWriter(text, fieldnames=['Text#','Title','Authors','Language','Subjects'])
        writer.writeheader()
        for number in range(1, count+1):
            writer.writerow({'Text#':number,'Title':'Libro '+str(number),
                'Authors':'Escritora, Ana, 1800-1890', 'Language':('es','en','ja')[number % 3],
                'Subjects':('Poetry','History','Juvenile fiction')[number % 3]})
        path = root/'catalog.csv.gz'
        path.write_bytes(gzip.compress(text.getvalue().encode()))
        return path

    def test_selection_is_diverse_deterministic_and_excludes_known_ids_and_pairs(self):
        with TemporaryDirectory() as raw:
            path = self.catalog(Path(raw))
            first = select_catalog(path, 6, {('libro 1','ana escritora')}, {'2'})
            self.assertEqual(first, select_catalog(path, 6, {('libro 1','ana escritora')}, {'2'}))
            self.assertEqual(len(first['selected']), 6)
            self.assertEqual(len(first['distribution']['language']), 3)
            self.assertFalse({'1','2'} & {item['id'] for item in first['selected']})
            self.assertEqual(first['counts']['already_known'], 2)

    def test_selection_uses_same_document_label_normalization_as_memory(self):
        with TemporaryDirectory() as raw:
            path = self.catalog(Path(raw), 1)
            text = gzip.decompress(path.read_bytes()).decode().replace('Libro 1', 'Libro 1 (Novela)')
            path.write_bytes(gzip.compress(text.encode()))
            report = select_catalog(path, 1, {('libro 1','ana escritora')})
            self.assertEqual(report['selected'], [])
            self.assertEqual(report['counts']['already_known'], 1)

    def test_selected_import_checkpoints_are_separate_and_replays_do_not_duplicate(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            path = self.catalog(root, 520)
            args = dict(state_database=root/'ledger.sqlite3', memory_database=root/'memory.sqlite3', languages=())
            one = import_catalog(path, selected_ids=['300','510'], max_records=1, **args)
            self.assertEqual(one['accepted'], 1)
            two = import_catalog(path, selected_ids=['510','300'], **args)
            self.assertEqual(two['accepted'], 1)
            self.assertEqual(two['offset_before'], 300)
            self.assertTrue(two['complete'])
            replay = import_catalog(path, selected_ids=['300','510'], **args)
            self.assertEqual(replay['accepted'], 0)
            other = import_catalog(path, selected_ids=['1'], **args)
            self.assertEqual(other['inserted'], 1)
            db = _connect(args['state_database'])
            try:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM acquisition_records').fetchone()[0], 3)
            finally:
                db.close()

    def test_invalid_selection_rejected_before_creating_files(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            path = self.catalog(root)
            with self.assertRaises(ValueError):
                import_catalog(path, selected_ids=['../1'], state_database=root/'ledger.sqlite3',
                               memory_database=root/'memory.sqlite3')
            self.assertFalse((root/'ledger.sqlite3').exists())

    def test_completed_csv_does_not_hide_pending_memory_outbox(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            path = self.catalog(root)
            args = dict(state_database=root/'ledger.sqlite3', memory_database=root/'memory.sqlite3', languages=())
            with patch('core.literary_acquisition.drain_projection', return_value={'projected': 0}):
                report = import_catalog(path, selected_ids=['1','2'], **args)
            self.assertTrue(report['complete'])
            self.assertEqual(pending_memory_projection(args['state_database']), 2)
            import_catalog(path, selected_ids=['1','2'], **args)
            self.assertEqual(pending_memory_projection(args['state_database']), 0)

    def test_subjects_are_not_inferred_from_title_and_birth_is_not_publication(self):
        self.assertEqual(genre(['Juvenile fiction']), 'juvenil')
        self.assertEqual(genre(['Poetry']), 'poesia')
        self.assertEqual(genre([]), 'otros')
        with TemporaryDirectory() as raw:
            item = select_catalog(self.catalog(Path(raw)), 1)['selected'][0]
            self.assertEqual(item['author_birth_century'], '1800')
            self.assertNotIn('publication_year', item)

    def check_rows(self, table, original, actual, columns=('id','value')):
        from .database_transfer import fingerprint, encode
        with TemporaryDirectory() as raw:
            root = Path(raw)
            (root/'database').mkdir()
            with gzip.open(root/'database'/'rows.gz', 'wt', encoding='utf-8') as stream:
                for row in original:
                    stream.write(json.dumps([encode(value) for value in row])+'\n')
            info = dict(fingerprint(table, list(columns), original, 'id'),
                        columns=list(columns), pk='id', file='rows.gz')
            with patch('core.database_transfer.table_rows', return_value=actual), \
                 patch('django.db.connection.check_constraints'):
                return preserve_expansion_rows(root, {'database':{'tables':{table: info}}})

    def test_integrity_allows_new_catalog_rows_but_not_changes_to_originals(self):
        self.assertEqual(self.check_rows('core_kbrecord', [('a','old')], [('a','old'),('b','new')])
                         ['core_kbrecord']['added'], 1)
        with self.assertRaises(ValueError):
            self.check_rows('core_kbrecord', [('a','old')], [('a','changed')])
        with self.assertRaises(ValueError):
            self.check_rows('core_kbrecord', [('a','old')], [])

    def test_integrity_rejects_changes_to_reader_tables_and_cursor_regression(self):
        with self.assertRaises(ValueError):
            self.check_rows('core_mensajeia', [('a','old')], [('a','old'),('b','new')])
        self.check_rows('core_kbprojection', [('a',5)], [('a',6)], ('id','last_rowid'))
        with self.assertRaises(ValueError):
            self.check_rows('core_kbprojection', [('a',5)], [('a',4)], ('id','last_rowid'))

    def test_memory_integrity_allows_additions_but_rejects_modified_original(self):
        from scripts.knowledge.audit_expansion import memory_integrity
        with TemporaryDirectory() as raw:
            original, current = Path(raw)/'before.sqlite3', Path(raw)/'after.sqlite3'
            for path in (original, current):
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute('CREATE TABLE memory_works (id TEXT PRIMARY KEY, value TEXT)')
                    db.execute("INSERT INTO memory_works VALUES ('one','original')")
            with closing(sqlite3.connect(current)) as db, db:
                db.execute("INSERT INTO memory_works VALUES ('two','new')")
            self.assertEqual(memory_integrity(original, current)['memory_works']['after'], 2)
            with closing(sqlite3.connect(current)) as db, db:
                db.execute("UPDATE memory_works SET value='changed' WHERE id='one'")
            with self.assertRaises(ValueError):
                memory_integrity(original, current)

    def test_source_audit_accepts_only_monotonic_validity_refresh_not_content_changes(self):
        from scripts.knowledge.audit_expansion import memory_integrity
        with TemporaryDirectory() as raw:
            original, current = Path(raw)/'before.sqlite3', Path(raw)/'after.sqlite3'
            for path in (original, current):
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute('CREATE TABLE memory_sources (id TEXT PRIMARY KEY, content_hash TEXT, retrieved_at REAL)')
                    db.execute("INSERT INTO memory_sources VALUES ('one','original',1)")
            with closing(sqlite3.connect(current)) as db, db:
                db.execute('UPDATE memory_sources SET retrieved_at=2')
            result = memory_integrity(original, current)
            self.assertEqual(result['memory_sources']['unchanged_content_validity_refreshed'], 1)
            with closing(sqlite3.connect(current)) as db, db:
                db.execute("UPDATE memory_sources SET content_hash='changed'")
            with self.assertRaises(ValueError):
                memory_integrity(original, current)
