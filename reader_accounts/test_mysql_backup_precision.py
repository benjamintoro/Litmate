from copy import deepcopy

from django.test import SimpleTestCase

from scripts.accounts.mysql_backup import restored_fingerprint
from scripts.accounts.prepare_mysql import fingerprint


class BackupDatePrecisionTests(SimpleTestCase):
    def row(self, value):
        return [{'model':'auth.user','pk':100,'fields':{'date_joined':value,'username':'synthetic'}}]

    def test_zero_fraction_is_the_same_instant(self):
        expected=self.row('2026-11-18T17:01:14.000Z')
        actual=self.row('2026-11-18T17:01:14Z')
        self.assertEqual(restored_fingerprint(expected,actual),fingerprint(expected))

    def test_different_millisecond_remains_a_failure(self):
        expected=self.row('2026-11-18T17:01:14.001Z')
        self.assertNotEqual(restored_fingerprint(expected,self.row('2026-11-18T17:01:14Z')),fingerprint(expected))

    def test_user_text_is_not_normalized(self):
        expected=self.row('2026-11-18T17:01:14Z')
        expected[0]['fields']['username']='2026-11-18T17:01:14.000Z'
        actual=deepcopy(expected)
        actual[0]['fields']['username']='2026-11-18T17:01:14Z'
        self.assertNotEqual(restored_fingerprint(expected,actual),fingerprint(expected))

    def test_verification_does_not_rewrite_restored_rows(self):
        expected=self.row('2026-11-18T17:01:14.000Z')
        actual=self.row('2026-11-18T17:01:14Z')
        original=deepcopy(actual)
        restored_fingerprint(expected,actual)
        self.assertEqual(original,actual)

    def test_missing_rows_and_changed_ids_are_rejected(self):
        expected=self.row('2026-11-18T17:01:14Z')
        self.assertNotEqual(restored_fingerprint(expected,[]),fingerprint(expected))
        actual=deepcopy(expected);actual[0]['pk']=101
        self.assertNotEqual(restored_fingerprint(expected,actual),fingerprint(expected))
