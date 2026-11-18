# SPDX-License-Identifier: GPL-2.0-only
import unittest

from prepare_annibale_os4_telephony import convert, sha, verify_edges


class TelephonyMigrationTest(unittest.TestCase):
    def setUp(self):
        self.before = {'proprietary-files.txt': 'system_ext/app/Old/Old.apk\nsystem_ext/priv-app/Phone/Phone.apk;REQUIRED=Compat\n',
                       'device.mk': '# Generic ramdisk allow list\noriginal product rules\n'}
        self.guard = '# tested SDK guard\n'
        self.profile = {'inputs': {k: sha(v.encode()) for k, v in self.before.items()},
                        'guard_sha256': sha(self.guard.encode()),
                        'retired_entry': 'system_ext/app/Old/Old.apk',
                        'retained_entries': ['system_ext/priv-app/Phone/Phone.apk;REQUIRED=Compat']}

    def test_preserves_provider_compat_and_product_rules(self):
        result = convert(self.before, self.profile, self.guard)
        self.assertEqual(result['proprietary-files.txt'], self.profile['retained_entries'][0] + '\n')
        self.assertEqual(result['device.mk'], self.guard + '\n' + self.before['device.mk'])

    def test_input_drift_rejected(self):
        self.before['device.mk'] += 'another rule\n'
        with self.assertRaises(ValueError):
            convert(self.before, self.profile, self.guard)

    def test_changed_guard_rejected(self):
        with self.assertRaises(ValueError):
            convert(self.before, self.profile, '# removed check\n')

    def test_repeat_rejected(self):
        after = convert(self.before, self.profile, self.guard)
        with self.assertRaises(ValueError):
            convert(after, self.profile, self.guard)

    def test_compat_dependency_loss_rejected(self):
        self.before['proprietary-files.txt'] = self.before['proprietary-files.txt'].replace(';REQUIRED=Compat', '')
        self.profile['inputs']['proprietary-files.txt'] = sha(self.before['proprietary-files.txt'].encode())
        with self.assertRaises(ValueError):
            convert(self.before, self.profile, self.guard)

    def test_call_edge_verified(self):
        expected = {'LPhone;->init(': ['LAudio;->start(']}
        self.assertEqual(verify_edges({'LPhone;->init()V': ['invoke-static v0, LAudio;->start()V']}, expected), expected)

    def test_string_literal_is_not_a_call(self):
        with self.assertRaises(ValueError):
            verify_edges({'LPhone;->init()V': ['const-string v0, "LAudio;->start()V"']}, {'LPhone;->init(': ['LAudio;->start(']})

    def test_missing_method_rejected(self):
        with self.assertRaises(ValueError):
            verify_edges({}, {'LPhone;->init(': ['LAudio;->start(']})

    def test_ambiguous_method_rejected(self):
        with self.assertRaises(ValueError):
            verify_edges({'LPhone;->init()V': [], 'LPhone;->init(I)V': []}, {'LPhone;->init(': []})


if __name__ == '__main__':
    unittest.main()
