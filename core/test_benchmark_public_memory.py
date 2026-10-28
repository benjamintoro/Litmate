import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import SimpleTestCase
from evaluar_chat_http import copy_public_memory_snapshot
from .literary_memory import initialize_store


class PublicMemoryBenchmarkTests(SimpleTestCase):
    def test_public_store_copy_does_not_modify_source(self):
        with TemporaryDirectory() as folder:
            source, target = Path(folder) / 'memory.sqlite3', Path(folder) / 'copy.sqlite3'
            initialize_store(source)
            before = source.read_bytes()
            report = copy_public_memory_snapshot(source, target)
            self.assertTrue(target.exists())
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(report['mode'], 'validated_public_memory_copy_source_readonly')

    def test_foreign_database_and_existing_target_are_rejected(self):
        with TemporaryDirectory() as folder:
            source, target = Path(folder) / 'private.sqlite3', Path(folder) / 'copy.sqlite3'
            with closing(sqlite3.connect(source)) as db, db:
                db.execute('CREATE TABLE sessions(secret TEXT)')
            with self.assertRaises(ValueError):
                copy_public_memory_snapshot(source, target)
            self.assertFalse(target.exists())
