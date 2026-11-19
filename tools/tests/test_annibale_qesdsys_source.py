# SPDX-License-Identifier: GPL-2.0-only
import tempfile
import unittest
from pathlib import Path

from prepare_annibale_qesdsys_source import check_policy, convert, pinned, sha, verify_apk
from audit_annibale_vendor_blobs import parse_list


class QesdSystemSourceTest(unittest.TestCase):
    def setUp(self):
        self.source = 'system_ext/app/FrameworksUtilsSysService/FrameworksUtilsSysService.apk'
        self.text = '# QESD\n' + self.source + '\nvendor/bin/qesdk-manager\nvendor/bin/qesdk-secmanager\n'
        self.profile = {'input_sha256': {'proprietary-files.txt': sha(self.text.encode())},
                        'old_entry': self.source, 'apk_source': self.source,
                        'apk_destination': self.source.replace('/app/', '/priv-app/'),
                        'apk_sha1': 'a' * 40, 'apk_sha256': 'b' * 64,
                        'package': 'vendor.qti.frameworks.utils',
                        'binder_instance': 'vendor.qti.qesdsys.IQesdSys/default'}
        self.seapp = 'user=system seinfo=platform name=vendor.qti.frameworks.utils isPrivApp=true domain=vendor_qesdk_app type=system_app_data_file\n'
        self.contexts = 'vendor.qti.qesdsys.IQesdSys/default u:object_r:vendor_qesdk_service:s0\n'
        self.te = 'add_service(vendor_qesdk_app, vendor_qesdk_service);\n'

    def test_privileged_mapping_keeps_managers_and_platform_signing(self):
        result = convert(self.text, self.profile)
        self.assertIn(self.source + ':' + self.profile['apk_destination'] + '|' + 'a' * 40, result)
        self.assertTrue(result.endswith('vendor/bin/qesdk-manager\nvendor/bin/qesdk-secmanager\n'))
        self.assertNotIn('PRESIGNED', result)
        self.assertNotIn('SKIPAPKCHECKS', result)
        self.assertEqual([e['source'] for e in parse_list(result) if e['section'] == 'QESD system service'], [self.source])
        self.assertTrue(all(e['section'] == 'QESD' for e in parse_list(result) if e['source'].startswith('vendor/')))

    def test_repeat_and_drift_rejected(self):
        with self.assertRaisesRegex(ValueError, 'list drift'):
            convert(convert(self.text, self.profile), self.profile)

    def test_ordinary_app_destination_rejected(self):
        self.profile['apk_destination'] = self.source
        with self.assertRaisesRegex(ValueError, 'privileged system_ext'):
            convert(self.text, self.profile)

    def test_policy_requires_privileged_platform_system_uid(self):
        self.assertEqual(check_policy(self.seapp, self.contexts, self.te, self.profile)['domain'], 'vendor_qesdk_app')
        for old, new in [('isPrivApp=true', 'isPrivApp=false'), ('user=system', 'user=_app'), ('seinfo=platform', 'seinfo=default')]:
            with self.subTest(old=old), self.assertRaisesRegex(ValueError, 'selector drift'):
                check_policy(self.seapp.replace(old, new), self.contexts, self.te, self.profile)

    def test_conflicting_selector_rejected(self):
        with self.assertRaisesRegex(ValueError, 'selector drift'):
            check_policy(self.seapp + self.seapp.replace('isPrivApp=true', 'isPrivApp=false'), self.contexts, self.te, self.profile)

    def test_wrong_service_context_and_missing_registration_rejected(self):
        with self.assertRaisesRegex(ValueError, 'binder context drift'):
            check_policy(self.seapp, self.contexts.replace('vendor_qesdk_service', 'default_android_service'), self.te, self.profile)
        with self.assertRaisesRegex(ValueError, 'registration rule'):
            check_policy(self.seapp, self.contexts, '', self.profile)

    def test_changed_stock_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'input').write_bytes(b'actual')
            with self.assertRaisesRegex(ValueError, 'unreviewed input'):
                pinned(root, {'input': sha(b'expected')})
            (root / 'alias').symlink_to(root / 'input')
            with self.assertRaisesRegex(ValueError, 'unsafe input'):
                pinned(root, {'alias': sha(b'actual')})

    def test_changed_apk_rejected_before_dex_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'changed.apk'
            p.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'unreviewed APK'):
                verify_apk(p, self.profile)


if __name__ == '__main__':
    unittest.main()
