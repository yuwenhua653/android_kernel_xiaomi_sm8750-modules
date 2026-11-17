# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import stat
import struct
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from annibale_ramdisk import read_newc, serial_bootconfig, vendor_v4


def cpio_member(name, data=b'', mode=stat.S_IFREG | 0o644):
    encoded = name.encode() + b'\0'
    fields = [1, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(encoded), 0]
    header = b'070701' + ''.join(f'{x:08x}' for x in fields).encode() + encoded
    header += bytes((-len(header)) % 4)
    return header + data + bytes((-len(data)) % 4)


def archive(name='lib/modules/example.ko', data=b'ELF fixture'):
    return cpio_member(name, data) + cpio_member('TRAILER!!!')


def vendor_fixture():
    data = bytearray(4 * 4096 + 5)
    data[:8] = b'VNDRBOOT'
    struct.pack_into('<II', data, 8, 4, 4096)
    struct.pack_into('<I', data, 24, 4)
    struct.pack_into('<II', data, 2096, 2128, 4)
    struct.pack_into('<4I', data, 2112, 108, 1, 108, 5)
    struct.pack_into('<III', data, 3 * 4096, 4, 0, 1)
    data[4096:4100], data[8192:8196], data[16384:] = b'CPIO', b'DTB!', b'x=1\n\n'
    return data


class RamdiskTests(unittest.TestCase):
    def test_valid_layout_and_nonzero_table(self):
        sections, report = vendor_v4(vendor_fixture())
        self.assertEqual(sections['ramdisk'], b'CPIO')
        self.assertEqual(report['entries'][0]['size'], 4)

    def test_zeroed_table_entry_rejected(self):
        data = vendor_fixture()
        data[12288:12396] = bytes(108)
        with self.assertRaisesRegex(ValueError, 'empty vendor ramdisk entry'):
            vendor_v4(data)

    def test_out_of_bounds_table_fragment_rejected(self):
        data = vendor_fixture()
        struct.pack_into('<I', data, 12292, 4)
        with self.assertRaisesRegex(ValueError, 'entry'):
            vendor_v4(data)

    def test_valid_newc_preserves_module_bytes(self):
        self.assertEqual(read_newc(archive())['lib/modules/example.ko']['data'], b'ELF fixture')

    def test_duplicate_archive_path_rejected(self):
        data = cpio_member('lib/a', b'first') + archive('lib/a', b'second')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            read_newc(data)

    def test_traversal_is_rejected_without_extraction(self):
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            read_newc(archive('../outside'))

    def test_symlink_member_is_rejected(self):
        data = cpio_member('lib/modules', b'elsewhere', stat.S_IFLNK | 0o777) + cpio_member('TRAILER!!!')
        with self.assertRaisesRegex(ValueError, 'nonregular'):
            read_newc(data)

    def test_missing_trailer_rejected(self):
        with self.assertRaisesRegex(ValueError, 'missing newc trailer'):
            read_newc(cpio_member('lib/a', b'test'))

    def test_concatenated_archive_rejected(self):
        with self.assertRaisesRegex(ValueError, 'payload after'):
            read_newc(archive() + archive())


class BootconfigTests(unittest.TestCase):
    def test_only_parallel_mode_changes(self):
        data = b'androidboot.hardware=qcom\nandroidboot.load_modules_parallel=true\nandroidboot.memcg=1\n'
        self.assertEqual(serial_bootconfig(data), data.replace(b'=true', b'=false'))

    def test_duplicate_setting_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            serial_bootconfig(b'androidboot.load_modules_parallel=true\nandroidboot.load_modules_parallel=false\n')

    def test_cmdline_conflict_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'command-line'):
            serial_bootconfig(b'androidboot.load_modules_parallel=true\n', 'androidboot.load_modules_parallel=true')

    def test_missing_or_unknown_mode_rejected(self):
        for data in (b'androidboot.hardware=qcom\n', b'androidboot.load_modules_parallel=auto\n'):
            with self.assertRaises(ValueError):
                serial_bootconfig(data)
