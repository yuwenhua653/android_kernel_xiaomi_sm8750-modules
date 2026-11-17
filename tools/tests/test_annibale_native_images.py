# SPDX-License-Identifier: GPL-2.0-only
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_annibale_native_images import check_fstab, verify_stage
from check_annibale_erofs import inspect

FSTAB = Path(__file__).resolve().parents[2] / 'configs/annibale/native/fstab.qcom'


class NativeFstabTests(unittest.TestCase):
    def test_reviewed_fstab(self):
        self.assertEqual(len(check_fstab(FSTAB.read_text())), 28)

    def test_dlkm_mount_and_avb_guards(self):
        original = 'vendor_dlkm /vendor_dlkm erofs ro wait,slotselect,avb=vbmeta,logical,first_stage_mount'
        for replacement in (original.replace('erofs', 'ext4'), original.replace(',first_stage_mount', ''),
                            original.replace(',avb=vbmeta', ''), original.replace(',slotselect', ''),
                            original.replace(',logical', ''), ''):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                check_fstab(FSTAB.read_text().replace(original, replacement))

    def test_encryption_guards(self):
        for old in ('fileencryption=aes-256-xts:aes-256-cts:v2+inlinecrypt_optimized+wrappedkey_v0',
                    'metadata_encryption=aes-256-xts:wrappedkey_v0'):
            with self.subTest(old=old), self.assertRaisesRegex(ValueError, 'encryption'):
                check_fstab(FSTAB.read_text().replace(old, 'encryptable=footer'))

    def test_stock_only_mount_rejected(self):
        for row in ('overlay /vendor overlay ro wait', 'userdata /data mifs rw wait'):
            with self.subTest(row=row), self.assertRaises(ValueError):
                check_fstab(FSTAB.read_text() + '\n' + row)

    def test_missing_metadata_rejected(self):
        text = '\n'.join(r for r in FSTAB.read_text().splitlines() if ' /metadata ' not in r)
        with self.assertRaisesRegex(ValueError, 'metadata'):
            check_fstab(text)


class StageBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stage = Path(self.tmp.name)
        data = json.dumps({'status': 'android_stage_passed', 'complete_device': False}).encode()
        (self.stage / 'validation.json').write_bytes(data)
        (self.stage / 'manifest.json').write_text(json.dumps({'validation.json': {
            'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}}))

    def test_valid_binding(self):
        self.assertFalse(verify_stage(self.stage)['complete_device'])

    def test_modified_file_rejected(self):
        (self.stage / 'validation.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'stale'):
            verify_stage(self.stage)

    def test_missing_file_rejected(self):
        (self.stage / 'validation.json').unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            verify_stage(self.stage)

    def test_extra_file_rejected(self):
        (self.stage / 'untracked.ko').write_bytes(b'wrong kernel')
        with self.assertRaisesRegex(ValueError, 'unrecorded'):
            verify_stage(self.stage)

    def test_symlink_rejected(self):
        (self.stage / 'alias').symlink_to('validation.json')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            verify_stage(self.stage)


@unittest.skipUnless(os.environ.get('ANNIBALE_TEST_EROFS'), 'set ANNIBALE_TEST_EROFS to a generated vendor_dlkm.img')
class RealErofsMutationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = Path(os.environ['ANNIBALE_TEST_EROFS']).read_bytes()
        cls.label = 'u:object_r:vendor_file:s0'
        cls.root = struct.unpack_from('<I', cls.data, 1064)[0] * 4096 + struct.unpack_from('<H', cls.data, 1038)[0] * 32

    def test_real_image(self):
        self.assertIn('/lib/modules/modules.load', inspect(self.data, self.label))

    def test_wrong_label(self):
        with self.assertRaisesRegex(ValueError, 'SELinux'):
            inspect(self.data, 'u:object_r:system_dlkm_file:s0')

    def test_wrong_mode(self):
        data = bytearray(self.data)
        struct.pack_into('<H', data, self.root + 4, 0o40777)
        with self.assertRaisesRegex(ValueError, 'mode'):
            inspect(data, self.label)

    def test_nonroot_owner(self):
        data = bytearray(self.data)
        struct.pack_into('<H', data, self.root + 24, 1000)
        with self.assertRaisesRegex(ValueError, 'owner'):
            inspect(data, self.label)

    def test_unsupported_features(self):
        data = bytearray(self.data)
        struct.pack_into('<I', data, 1104, 0x80000001)
        with self.assertRaisesRegex(ValueError, 'features'):
            inspect(data, self.label)

    def test_truncated_image(self):
        with self.assertRaises(ValueError):
            inspect(self.data[:-4096], self.label)

    def test_outside_metadata(self):
        data = bytearray(self.data)
        struct.pack_into('<I', data, 1064, len(data) // 4096)
        with self.assertRaisesRegex(ValueError, 'extent'):
            inspect(data, self.label)


if __name__ == '__main__':
    unittest.main()
