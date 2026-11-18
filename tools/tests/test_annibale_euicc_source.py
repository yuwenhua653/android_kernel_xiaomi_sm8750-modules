# SPDX-License-Identifier: GPL-2.0-only
import copy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from prepare_annibale_euicc_source import ANDROID, convert, digest, verify_apk, verify_manifest


class EuiccSourceTest(unittest.TestCase):
    def setUp(self):
        self.old = 'mi_ext/product/priv-app/E/E.apk:product/priv-app/E/E.apk;PRESIGNED'
        self.before = {'proprietary-files.txt': '# Euicc\n' + self.old + '\n\n# Other\nvendor/lib64/retain.so\n'}
        self.profile = {'input_sha256': {n: digest(v.encode()) for n, v in self.before.items()},
                        'old_entry': self.old, 'new_source': 'product/priv-app/E/E.apk', 'sha1': 'a' * 40,
                        'package': 'com.google.android.euicc', 'version_code': '1', 'min_sdk': '29',
                        'target_sdk': '35', 'euicc_service': 'example.LPA', 'optional_libraries': ['optional'],
                        'privileged_permissions': ['android.permission.WRITE_EMBEDDED_SUBSCRIPTIONS']}
        self.manifest = ET.fromstring('''<manifest xmlns:android="http://schemas.android.com/apk/res/android"
            package="com.google.android.euicc" android:versionCode="1">
            <uses-sdk android:minSdkVersion="29" android:targetSdkVersion="35"/>
            <application><uses-library android:name="optional" android:required="false"/>
            <service android:name="example.LPA" android:permission="android.permission.BIND_EUICC_SERVICE"
              android:exported="true"><intent-filter android:priority="100">
            <action android:name="android.service.euicc.EuiccService"/>
            </intent-filter></service></application></manifest>''')
        self.allowlist = '<permissions><privapp-permissions package="com.google.android.euicc"><permission name="android.permission.WRITE_EMBEDDED_SUBSCRIPTIONS"/></privapp-permissions></permissions>'

    def test_relocation_pins_bytes_preserves_signing_and_other_inputs(self):
        result = convert(self.before, self.profile)
        self.assertEqual(result, self.before['proprietary-files.txt'].replace(
            self.old, 'product/priv-app/E/E.apk;PRESIGNED|' + 'a' * 40))

    def test_input_drift_and_repeat_rejected(self):
        self.before['proprietary-files.txt'] = convert(self.before, self.profile)
        with self.assertRaisesRegex(ValueError, 'unreviewed input'):
            convert(self.before, self.profile)

    def test_re_signing_entry_rejected(self):
        self.before['proprietary-files.txt'] = self.before['proprietary-files.txt'].replace(';PRESIGNED', '')
        self.profile['old_entry'] = self.old.replace(';PRESIGNED', '')
        self.profile['input_sha256']['proprietary-files.txt'] = digest(self.before['proprietary-files.txt'].encode())
        with self.assertRaisesRegex(ValueError, 'ambiguous eSIM provider'):
            convert(self.before, self.profile)

    def test_real_lpa_contract(self):
        self.assertTrue(verify_manifest(self.manifest, self.allowlist, self.profile)['binding_permission_checked'])

    def test_policy_only_application_rejected(self):
        app = self.manifest.find('application')
        app.remove(app.find('service'))
        with self.assertRaisesRegex(ValueError, 'LPA service'):
            verify_manifest(self.manifest, self.allowlist, self.profile)

    def test_unprotected_or_unselectable_service_rejected(self):
        for attr, value in [('permission', 'wrong'), ('exported', 'false')]:
            with self.subTest(attr=attr):
                manifest = copy.deepcopy(self.manifest)
                manifest.find('application/service').set(ANDROID + attr, value)
                with self.assertRaisesRegex(ValueError, 'LPA service'):
                    verify_manifest(manifest, self.allowlist, self.profile)
        self.manifest.find('application/service/intent-filter').set(ANDROID + 'priority', '0')
        with self.assertRaisesRegex(ValueError, 'cannot be selected'):
            verify_manifest(self.manifest, self.allowlist, self.profile)

    def test_missing_privilege_rejected(self):
        allowlist = self.allowlist.replace('android.permission.WRITE_EMBEDDED_SUBSCRIPTIONS', 'wrong')
        with self.assertRaisesRegex(ValueError, 'privileged permission'):
            verify_manifest(self.manifest, allowlist, self.profile)

    def test_required_library_drift_rejected(self):
        self.manifest.find('application/uses-library').set(ANDROID + 'required', 'true')
        with self.assertRaisesRegex(ValueError, 'library dependency'):
            verify_manifest(self.manifest, self.allowlist, self.profile)

    def test_corrupt_input_rejected_before_signer_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            apk = Path(tmp) / 'bad.apk'
            apk.write_bytes(b'bad')
            self.profile.update(size=3, sha256='0' * 64)
            with self.assertRaisesRegex(ValueError, 'corrupted APK'):
                verify_apk(apk, self.profile, 'must-not-run', self.allowlist)


if __name__ == '__main__':
    unittest.main()
