"""Activation process configuration; no network, credentials or real DB writes."""
from unittest import TestCase
from iniciar_mysql_local import local_database_environment


class LocalMySQLActivationTests(TestCase):
    def test_google_no_billing_confirmation_is_explicit_and_process_only(self):
        env={'LITMATE_USE_GOOGLE_BOOKS_API':'False','UNRELATED':'kept'}
        before=dict(env)
        with local_database_environment('fake-local',env,google_books_no_billing=True):
            self.assertEqual(env['LITMATE_GOOGLE_BOOKS_CONFIRMED_NO_BILLING'],'True')
            self.assertEqual(env['LITMATE_USE_GOOGLE_BOOKS_API'],'True')
        self.assertEqual(env,before)

    def test_explicit_local_overrides_remote_only_inside_context(self):
        env = {'DB_HOST': 'remote.example', 'DB_NAME': 'old', 'DB_PASSWORD': 'fake-remote',
               'DB_SSL_CA': 'remote-ca', 'USE_SQLITE': 'False', 'UNRELATED': 'preserved'}
        before = dict(env)
        with local_database_environment('fake-local', env):
            self.assertEqual(env['DB_HOST'], '127.0.0.1')
            self.assertEqual(env['DB_NAME'], 'litmate_db')
            self.assertEqual(env['DB_ENGINE'], 'mysql')
            self.assertEqual(env['DB_PASSWORD'], 'fake-local')
            self.assertEqual(env['DB_MYSQL_DRIVER'], 'mysqlclient')
            self.assertEqual(env['DB_SSL_CA'], '')
        self.assertEqual(env, before)

    def test_exception_restores_original_environment(self):
        env = {}
        with self.assertRaises(RuntimeError):
            with local_database_environment('fake-local', env):
                raise RuntimeError('simulated startup failure')
        self.assertEqual(env, {})

    def test_missing_local_password_cannot_reuse_the_remote_one(self):
        env = {'DB_PASSWORD': 'fake-remote'}
        with self.assertRaises(ValueError):
            with local_database_environment('', env):
                pass
        self.assertEqual(env, {'DB_PASSWORD': 'fake-remote'})

    def test_http_development_mode_is_explicit_and_reversible(self):
        env = {'DEBUG': 'False'}
        with local_database_environment('fake-local', env):
            self.assertEqual(env['DEBUG'], 'False')
        with local_database_environment('fake-local', env, development_http=True):
            self.assertEqual(env['DEBUG'], 'True')
        self.assertEqual(env, {'DEBUG': 'False'})
