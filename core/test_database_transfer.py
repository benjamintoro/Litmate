"""Database transfer tests use new temporary SQLite files, never project data."""
from copy import deepcopy
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
from unittest import TestCase
from unittest.mock import MagicMock
import json
import os
import subprocess
import sys

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from litmate_project.database_settings import database_config
from .database_transfer import (TransferError, temporary_alias, export_database, import_database,
    compare_database, verify_export, snapshot_sqlite, fingerprint, insertion_order, safe_file)


class DatabaseConfigTests(TestCase):
    def test_sqlite_default_without_database_environment(self):
        self.assertTrue(database_config(Path.cwd(), {})['ENGINE'].endswith('sqlite3'))

    def test_explicit_sqlite_wins_over_legacy_cloud_environment(self):
        cfg = database_config(Path.cwd(), {'DB_ENGINE': 'sqlite', 'USE_SQLITE': 'False', 'DB_HOST': 'old',
                                         'DB_SQLITE_PATH': 'my-copy.sqlite3'})
        self.assertTrue(cfg['ENGINE'].endswith('sqlite3'))
        self.assertEqual(cfg['NAME'], Path.cwd() / 'my-copy.sqlite3')

    def test_existing_cloud_selection_is_preserved(self):
        cfg = database_config(Path.cwd(), {'DB_HOST': 'cloud.example', 'DB_NAME': 'old', 'DB_USER': 'old'})
        self.assertEqual(cfg['PORT'], '4000')
        self.assertIn('ssl', cfg['OPTIONS'])

    def test_local_mysql_does_not_inherit_cloud_tls_or_port(self):
        cfg = database_config(Path.cwd(), {'DB_ENGINE': 'mysql', 'DB_NAME': 'litmate_db',
                                         'DB_USER': 'litmate_app', 'DB_PASSWORD': 'test-only'})
        self.assertEqual(cfg['PORT'], '3306')
        self.assertEqual(cfg['HOST'], '127.0.0.1')
        self.assertEqual(cfg['OPTIONS']['charset'], 'utf8mb4')
        self.assertNotIn('ssl', cfg['OPTIONS'])
        self.assertIn('STRICT_TRANS_TABLES', cfg['OPTIONS']['init_command'])

    def test_invalid_engine_and_missing_identity_fail_closed(self):
        for env in ({'DB_ENGINE': 'invalid'}, {'DB_ENGINE': 'mysql'}):
            with self.subTest(env=env), self.assertRaises(ImproperlyConfigured):
                database_config(Path.cwd(), env)

    def test_driver_selection_preserves_remote_tls_and_prefers_native_locally(self):
        for host, driver, expected in [('127.0.0.1', 'auto', 'MySQLdb'),
                                       ('legacy.example', 'auto', 'pymysql'),
                                       ('legacy.example', 'mysqlclient', 'MySQLdb')]:
            with self.subTest(host=host, driver=driver):
                env = dict(os.environ, DB_HOST=host, DB_MYSQL_DRIVER=driver)
                result = subprocess.run([sys.executable, '-B', '-c',
                    'import litmate_project,MySQLdb; print(MySQLdb.__name__)'],
                    env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout.strip(), expected)


class TransferHelpersTests(TestCase):
    def test_tidb_auth_permission_status_zero_is_not_its_actual_next_id(self):
        """Observed values: 132 rows, max=120008, SQLite seq=150000, next=150001."""
        from .database_transfer import next_id_value
        db = MagicMock(vendor='mysql', mysql_server_info='8.0.11-TiDB-v8.5.3')
        cursor = db.cursor.return_value.__enter__.return_value
        def execute(sql, params=None):
            if sql.startswith('SHOW CREATE TABLE'):
                cursor.fetchone.return_value = ('auth_permission',
                    'CREATE TABLE auth_permission (id int AUTO_INCREMENT PRIMARY KEY) ENGINE=InnoDB AUTO_INCREMENT=150001')
            else:
                cursor.description = [('Name',), ('Auto_increment',)]
                cursor.fetchone.return_value = ('auth_permission', 0)
        cursor.execute.side_effect = execute
        self.assertEqual(next_id_value(db, 'auth_permission'), 150001)

    def test_sqlite_sequence_is_last_used_while_mysql_value_is_next(self):
        from .database_transfer import next_id_value
        db = MagicMock(vendor='sqlite')
        db.cursor.return_value.__enter__.return_value.fetchone.return_value = (150000,)
        self.assertEqual(next_id_value(db, 'auth_permission'), 150001)
    def test_mysql_metadata_cache_is_disabled_only_for_supported_mysql(self):
        from .database_transfer import fresh_mysql_metadata
        db = MagicMock(vendor='mysql', mysql_version=(8, 0, 46), mysql_is_mariadb=False,
                       mysql_server_info='8.0.46')
        fresh_mysql_metadata(db)
        db.cursor.return_value.__enter__.return_value.execute.assert_called_once_with(
            'SET SESSION information_schema_stats_expiry=0')
        db.cursor.reset_mock()
        db.mysql_server_info = '8.0.11-TiDB-v8.5.3'
        fresh_mysql_metadata(db)
        db.cursor.assert_not_called()
    def test_sqlite_online_backup_includes_wal_and_keeps_source(self):
        with TemporaryDirectory() as folder:
            source, target = Path(folder) / 'source.db', Path(folder) / 'copy.db'
            with closing(sqlite3.connect(source)) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE facts(id INTEGER PRIMARY KEY, text TEXT)')
                db.execute('INSERT INTO facts VALUES(7, ?)', ('á文🙂',))
                db.commit()
                info = snapshot_sqlite(source, target)
                self.assertEqual(info['counts']['facts'], 1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM facts').fetchone()[0], 1)
            with self.assertRaises(TransferError):
                snapshot_sqlite(source, target)

    def test_missing_source_does_not_create_an_empty_sqlite_database(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'missing.db'
            with self.assertRaises(TransferError):
                snapshot_sqlite(path, Path(folder) / 'copy.db')
            self.assertFalse(path.exists())

    def test_fingerprint_ignores_row_column_order_but_not_case_or_values(self):
        a = fingerprint('unknown', ['id', 'text'], [(1, 'á'), (2, 'b')], 'id')
        b = fingerprint('unknown', ['text', 'id'], [('b', 2), ('á', 1)], 'id')
        self.assertEqual(a, b)
        self.assertNotEqual(a, fingerprint('unknown', ['id', 'text'], [(1, 'Á'), (2, 'b')], 'id'))

    def test_cyclic_relations_and_path_escape_are_rejected(self):
        with self.assertRaises(TransferError):
            insertion_order({'a': {'constraints': {'fk': {'foreign_key': ('a', 'id')}}}})
        with TemporaryDirectory() as folder, self.assertRaises(TransferError):
            safe_file(folder, '../outside')


class DatabaseTransferIntegrationTests(TestCase):
    @override_settings(MIGRATION_MODULES={})
    def test_migrated_schema_roundtrip_preserves_pk_fk_m2m_and_rejects_overwrite(self):
        from django.db.migrations.executor import MigrationExecutor
        with TemporaryDirectory() as folder:
            config = {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(Path(folder) / 'source.db'),
                      'OPTIONS': {}, 'USER': '', 'PASSWORD': '', 'HOST': '', 'PORT': ''}
            with temporary_alias('source_transfer_test', config) as source:
                executor = MigrationExecutor(source)
                executor.migrate(executor.loader.graph.leaf_nodes())
                with source.cursor() as cur:
                    cur.execute('INSERT INTO core_genero(id,nombre,slug,descripcion) VALUES(%s,%s,%s,%s)',
                                [42, 'Ficción 🙂', 'fiction', None])
                    cur.execute("UPDATE sqlite_sequence SET seq=9000 WHERE name='core_genero'")
                from django.contrib.auth.models import User
                from .models import Autor, Libro, Genero, LibroFavorito
                from suscripciones.models import PlanSuscripcion, SuscripcionUsuario
                from decimal import Decimal
                user = User.objects.using(source.alias).create(id=51, username='test-only',
                            password='test-hash-no-real-secret', email='local@example.test')
                author = Autor.objects.using(source.alias).create(id=61, nombre='Autora á文🙂')
                book = Libro.objects.using(source.alias).create(id=71, autor=author, titulo='Obra de prueba')
                book.generos.add(Genero.objects.using(source.alias).get(pk=42))
                LibroFavorito.objects.using(source.alias).create(usuario=user, libro=book)
                plan = PlanSuscripcion.objects.using(source.alias).create(id=81, nombre='Prueba',
                            slug='prueba', precio=Decimal('123.45'))
                SuscripcionUsuario.objects.using(source.alias).create(usuario=user, plan=plan,
                            metadatos={'nested': {'accent': 'é文🙂'}, 'valid': True})
                meta = export_database(source.alias, Path(folder) / 'export')
                verify_export(Path(folder) / 'export', meta)
                config['NAME'] = str(Path(folder) / 'target.db')
                with temporary_alias('target_transfer_test', config) as target:
                    # Simulate a previous DDL-only attempt, without deleting anything.
                    executor = MigrationExecutor(target)
                    executor.migrate(executor.loader.graph.leaf_nodes())
                    with self.assertRaises(TransferError):
                        import_database(target, Path(folder) / 'export', meta)
                    imported = import_database(target, Path(folder) / 'export', meta, resume_empty=True)
                    self.assertEqual(imported['core_genero']['count'], 1)
                    self.assertEqual(imported['core_libro_generos']['count'], 1)
                    self.assertEqual(imported['core_librofavorito']['count'], 1)
                    with target.cursor() as cursor:
                        cursor.execute('SELECT password FROM auth_user WHERE id=51')
                        self.assertEqual(cursor.fetchone()[0], 'test-hash-no-real-secret')
                        cursor.execute('SELECT precio FROM suscripciones_plansuscripcion WHERE id=81')
                        self.assertEqual(Decimal(str(cursor.fetchone()[0])), Decimal('123.45'))
                        cursor.execute("SELECT seq FROM sqlite_sequence WHERE name='core_genero'")
                        self.assertEqual(cursor.fetchone()[0], 9000)
                    compare_database(target, Path(folder) / 'export', meta)
                    with self.assertRaises(TransferError):
                        import_database(target, Path(folder) / 'export', meta)
                    with self.assertRaises(TransferError):
                        import_database(target, Path(folder) / 'export', meta, resume_empty=True)
                    with target.cursor() as cursor:
                        cursor.execute("UPDATE auth_user SET password='modified-test-value' WHERE id=51")
                    with self.assertRaises(TransferError):
                        compare_database(target, Path(folder) / 'export', meta)
                config['NAME'] = str(Path(folder) / 'fresh-target.db')
                with temporary_alias('fresh_transfer_test', config) as target:
                    def no_destructive_sql(execute, sql, params, many, context):
                        self.assertFalse(sql.lstrip().upper().startswith(('DROP ', 'TRUNCATE ', 'DELETE ')), sql)
                        return execute(sql, params, many, context)
                    with target.execute_wrapper(no_destructive_sql):
                        imported = import_database(target, Path(folder) / 'export', meta)
                    self.assertEqual(imported['core_genero']['next_id'], 9001)
                    self.assertEqual(imported['auth_user']['count'], 1)
                path = Path(folder) / 'export' / meta['tables']['core_genero']['file']
                with path.open('ab') as stream:
                    stream.write(b'changed')
                with self.assertRaises(TransferError):
                    verify_export(Path(folder) / 'export', meta)
