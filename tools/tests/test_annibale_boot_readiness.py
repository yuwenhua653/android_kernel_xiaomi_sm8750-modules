# SPDX-License-Identifier: GPL-2.0-only
import hashlib
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_annibale_normal_boot import select
from prepare_annibale_boot_candidate import assemble
import capture_annibale_boot_readiness as capture


def record(name, path, sha):
    return {'name': name, 'paths': [path], 'sha256': sha}


class ProviderSelection(unittest.TestCase):
    def test_recovery_and_flatten_are_not_normal_providers(self):
        rows = [record('x', 'recovery/lib/modules/x.ko', '1'),
                record('x', 'system_dlkm/flatten/lib/modules/x.ko', '2'),
                record('x', 'vendor_dlkm/lib/modules/x.ko', '3')]
        selected, conditions, errors = select(rows, [])
        self.assertEqual(selected['x']['sha256'], '3')
        self.assertFalse(conditions or errors)

    def test_zram_needs_actual_early_load_evidence(self):
        rows = [record('zram', 'vendor_boot/lib/modules/zram.ko', '1'),
                record('zram', 'system_dlkm/lib/modules/r/zram.ko', '2')]
        selected, conditions, errors = select(rows, ['zram'])
        self.assertEqual(selected['zram']['sha256'], '1')
        self.assertEqual(len(conditions), 1)
        self.assertFalse(errors)
        self.assertTrue(select(rows, [])[2])
        self.assertEqual(len(rows), 2)  # inventory is not silently rewritten

    def test_unknown_duplicate_and_extra_variant_fail_closed(self):
        rows = [record('x', 'vendor_boot/lib/modules/x.ko', '1'),
                record('x', 'vendor_dlkm/lib/modules/x.ko', '2')]
        self.assertTrue(select(rows, ['x'])[2])
        rows = [record('zram', r['paths'][0], r['sha256']) for r in rows]
        rows.append(record('zram', 'system_dlkm/lib/modules/zram.ko', '3'))
        self.assertTrue(select(rows, ['zram'])[2])


class Candidate(unittest.TestCase):
    def setUp(self):
        self.stock = bytearray(32768)
        self.stock[:8] = b'ANDROID!'
        struct.pack_into('<4I', self.stock, 8, 64, 0, 0, 1584)
        struct.pack_into('<I', self.stock, 40, 4)
        self.stock[4096 + 56:4096 + 60] = b'ARMd'
        struct.pack_into('>4sIIQQQ', self.stock, len(self.stock) - 64,
                         b'AVBf', 1, 0, 8192, 8192, 256)
        self.kernel = bytearray(4100)
        self.kernel[56:60] = b'ARMd'

    def build(self):
        return assemble(self.stock, self.kernel, hashlib.sha256(self.stock).hexdigest(),
                        hashlib.sha256(self.kernel).hexdigest())

    def test_only_kernel_size_header_field_changes(self):
        image, report = self.build()
        self.assertEqual(image[:8], self.stock[:8])
        self.assertEqual(image[12:4096], self.stock[12:4096])
        self.assertEqual(image[4096:8196], self.kernel)
        self.assertEqual(len(image) % 4096, 0)
        self.assertNotEqual(image[-64:-60], b'AVBf')
        self.assertFalse(report['flash_ready'])

    def test_reject_wrong_hash_even_for_valid_layout(self):
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            assemble(self.stock, self.kernel)

    def test_reject_ramdisk_signature_version_reserved_and_compressed_kernel(self):
        original = bytes(self.stock)
        for offset, value in ((12, 1), (1580, 1), (40, 3), (24, 1)):
            self.stock[:] = original
            struct.pack_into('<I', self.stock, offset, value)
            with self.assertRaises(ValueError):
                self.build()
        self.stock[:] = original
        self.kernel[56:60] = b'xxxx'
        with self.assertRaises(ValueError):
            self.build()

    def test_reject_truncated_avb_extent(self):
        struct.pack_into('>Q', self.stock, len(self.stock) - 64 + 28, 999999)
        with self.assertRaises(ValueError):
            self.build()


class ReadOnlyCapture(unittest.TestCase):
    def test_device_selection_rejects_unauthorized_multiple_and_absent(self):
        self.assertEqual(capture.choose_device('List of devices attached\nABC device\n'), 'ABC')
        for rows in ('', 'ABC unauthorized', 'ABC offline', 'A device\nB device'):
            with self.assertRaises(ValueError):
                capture.choose_device('List of devices attached\n' + rows)

    def test_mount_filter_and_mifs_gate(self):
        rows = capture.filtered_mounts('/dev/a /data mifs rw,x 0 0\n'
                                       '/dev/b /storage/private f2fs rw 0 0\n')
        self.assertEqual(rows, [{'mountpoint': '/data', 'filesystem': 'mifs', 'read_only': False}])
        self.assertEqual(capture.assess({}, rows)['userdata_check'], 'blocked_mifs_not_in_candidate')
        self.assertEqual(capture.assess({}, [])['userdata_check'], 'needs_review')
        self.assertFalse(capture.assess({}, rows)['flash_ready'])

    def test_queries_are_read_only_and_strip_private_transport_and_module_addresses(self):
        calls = []
        def fake(argv):
            calls.append(argv)
            command = argv[4:]
            value = ''
            if command[0] == 'getprop':
                value = 'annibale' if command[1] == 'ro.product.device' else ''
            elif command == ['cat', '/proc/mounts']:
                value = '/dev/a /data f2fs rw 0 0'
            elif command == ['cat', '/proc/modules']:
                value = 'goodix_core 123 0 - Live 0xffffff00112233'
            elif command == ['cat', '/sys/class/input/input*/name']:
                value = 'goodix_ts\nAlice personal keyboard'
            return {'status': 'ok', 'stdout': value, 'stderr': 'SERIAL_TEST'}
        with patch.object(capture, 'execute', fake):
            report = capture.capture('adb', 'SERIAL_TEST')
        import json
        encoded = json.dumps(report)
        self.assertNotIn('SERIAL_TEST', encoded)
        self.assertNotIn('Alice', encoded)
        self.assertNotIn('ffffff00112233', encoded)
        self.assertEqual(report['loaded_module_names'], ['goodix_core'])
        self.assertEqual(report['touch_input_names'], ['goodix_ts'])
        self.assertTrue(all(c[3] == 'shell' and c[4] in
                            {'getprop', 'uname', 'getenforce', 'cat'} for c in calls))


if __name__ == '__main__':
    unittest.main()
