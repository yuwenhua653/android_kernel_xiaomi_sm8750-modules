# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_annibale_os4_authsecret import convert, verify_assets, OLD_MANIFEST, NEW_MANIFEST, OLD_LIBRARY, NEW_LIBRARY, EXISTING_LIBRARY


class AuthSecretTests(unittest.TestCase):
    def list_text(self):
        return '\n'.join(['# Existing service remains', 'odm/bin/hw/vendor.xiaomi.hardware.authsecretd',
                          OLD_MANIFEST, OLD_LIBRARY, EXISTING_LIBRARY, 'vendor/lib64/keep.so', ''])

    def test_only_reviewed_list_entries_change(self):
        after = convert(self.list_text())
        self.assertNotIn(OLD_MANIFEST, after)
        self.assertNotIn(OLD_LIBRARY, after)
        self.assertIn(NEW_MANIFEST+'\n', after)
        self.assertIn(NEW_LIBRARY+'\n', after)
        self.assertIn('odm/bin/hw/vendor.xiaomi.hardware.authsecretd\n', after)
        self.assertTrue(after.endswith('vendor/lib64/keep.so\n'))

    def test_already_converted_or_new_owner_rejected(self):
        for text in (convert(self.list_text()), self.list_text()+NEW_LIBRARY+'\n'):
            with self.assertRaises(ValueError): convert(text)

    def test_changed_owner_or_flags_rejected(self):
        for old in (OLD_MANIFEST, OLD_LIBRARY, EXISTING_LIBRARY):
            with self.assertRaises(ValueError): convert(self.list_text().replace(old,old+';EXTRACT_ONLY'))

    def test_asset_and_property_guards(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for part, name in [('vendor','build.prop'),('odm','etc/build.prop')]:
                p=root/part/name;p.parent.mkdir(parents=True,exist_ok=True)
                p.write_text(f'ro.{part}.build.version.incremental=OS4.0.6.0.XPKCN\n')
            p=root/NEW_LIBRARY;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture')
            manifest={'firmware_label':'OS4.0.6.0.XPKCNXM','incremental':'OS4.0.6.0.XPKCN',
                      'files':{NEW_LIBRARY:{'size':7,'sha256':hashlib.sha256(b'fixture').hexdigest()}}}
            verify_assets(root,manifest)
            p.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'hash mismatch'): verify_assets(root,manifest)
            p.write_bytes(b'fixture');(root/'vendor/build.prop').write_text('ro.vendor.build.version.incremental=OS3\n')
            with self.assertRaisesRegex(ValueError,'build mismatch'): verify_assets(root,manifest)

    def test_missing_final_newline_rejected(self):
        with self.assertRaisesRegex(ValueError,'newline'): convert(self.list_text().rstrip('\n'))
