#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Corrupted/mismatched module fixtures must not pass link qualification."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify_annibale_modules import module_info, verify


def elf_module(path, name, crc=0x12345678, release='6.6.test', depends='', machine=183):
    names = b'\0.shstrtab\0.modinfo\0__versions\0'
    info = f'name={name}\0vermagic={release} SMP modversions aarch64\0depends={depends}\0'.encode()
    versions = struct.pack('<Q56s', crc, b'module_layout')
    payloads = [b'', names, info, versions]
    offsets = [0, 64, 64 + len(names), 64 + len(names) + len(info)]
    shoff = offsets[3] + len(versions)
    header = struct.pack('<16sHHIQQQIHHHHHH', b'\x7fELF\x02\x01\x01' + b'\0' * 9,
                         1, machine, 1, 0, 0, shoff, 0, 64, 0, 0, 64, 4, 1)
    tables = b''
    for i, label in enumerate([b'', b'.shstrtab', b'.modinfo', b'__versions']):
        tables += struct.pack('<IIQQQQIIQQ', names.index(label) if label else 0,
                              3 if i == 1 else 1, 0, 0, offsets[i], len(payloads[i]),
                              0, 0, 1, 0)
    path.write_bytes(header + b''.join(payloads) + tables)


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.kernel, self.stage = self.root / 'kernel', self.root / 'stage'
        (self.kernel / 'include/config').mkdir(parents=True)
        self.stage.mkdir()
        (self.kernel / '.config').write_text('CONFIG_MODVERSIONS=y\n')
        (self.kernel / 'include/config/kernel.release').write_text('6.6.test\n')
        (self.kernel / 'Module.symvers').write_text('0x12345678\tmodule_layout\tvmlinux\tEXPORT_SYMBOL\n')
        (self.stage / 'Module.symvers').write_text('0x33333333\tprovider_api\tprovider\tEXPORT_SYMBOL\n')
        (self.kernel / 'modules.order').write_text('provider.o\n')
        (self.stage / 'modules.order').write_text(str(self.stage / 'consumer.o') + '\n')
        elf_module(self.kernel / 'provider.ko', 'provider')
        elf_module(self.stage / 'consumer.ko', 'consumer', depends='provider')

    def test_valid_and_stale_files_ignored(self):
        (self.stage / 'stale.ko').write_bytes(b'not a module')
        report = verify(self.kernel, self.stage)
        self.assertEqual(report['kernel_module_count'], 1)
        self.assertEqual(report['external_module_count'], 1)
        self.assertLess(report['dependency_order'].index('provider'),
                        report['dependency_order'].index('consumer'))

    def test_cyclic_dependencies_rejected(self):
        elf_module(self.kernel / 'provider.ko', 'provider', depends='consumer')
        with self.assertRaisesRegex(ValueError, 'cyclic module dependencies'):
            verify(self.kernel, self.stage)

    def test_self_dependency_rejected(self):
        elf_module(self.stage / 'consumer.ko', 'consumer', depends='consumer')
        with self.assertRaisesRegex(ValueError, 'cyclic module dependencies'):
            verify(self.kernel, self.stage)

    def test_btf_required_by_target_config(self):
        (self.kernel / '.config').write_text('CONFIG_MODVERSIONS=y\nCONFIG_DEBUG_INFO_BTF_MODULES=y\n')
        with self.assertRaisesRegex(ValueError, 'required module BTF'):
            verify(self.kernel, self.stage)

    def test_crc_mismatch_rejected(self):
        elf_module(self.stage / 'consumer.ko', 'consumer', crc=0x87654321)
        with self.assertRaisesRegex(ValueError, 'CRC'):
            verify(self.kernel, self.stage)

    def test_kernel_hyphen_underscore_dependency_names(self):
        elf_module(self.kernel / 'provider.ko', 'some_provider')
        elf_module(self.stage / 'consumer.ko', 'consumer', depends='some-provider')
        report = verify(self.kernel, self.stage)
        self.assertEqual(report['modules']['consumer']['depends'], ['some_provider'])

    def test_wrong_release_rejected(self):
        elf_module(self.stage / 'consumer.ko', 'consumer', release='6.6.other')
        with self.assertRaisesRegex(ValueError, 'wrong release'):
            verify(self.kernel, self.stage)

    def test_missing_dependency_rejected(self):
        elf_module(self.stage / 'consumer.ko', 'consumer', depends='absent_provider')
        with self.assertRaisesRegex(ValueError, 'unresolved module dependencies'):
            verify(self.kernel, self.stage)

    def test_equal_crc_does_not_allow_two_export_providers(self):
        # R12's msm_video and video variants linked but exported the same API.
        # Equal CRCs do not make simultaneous providers loadable.
        with (self.stage / 'Module.symvers').open('a') as stream:
            stream.write('0x33333333\tprovider_api\talternative\tEXPORT_SYMBOL\n')
        with self.assertRaisesRegex(ValueError, 'duplicate symbol provider'):
            verify(self.kernel, self.stage)

    def test_wrong_architecture_rejected(self):
        elf_module(self.stage / 'consumer.ko', 'consumer', machine=62)
        with self.assertRaisesRegex(ValueError, 'ARM64'):
            module_info(self.stage / 'consumer.ko')

    def test_truncated_sections_rejected(self):
        p = self.stage / 'consumer.ko'
        p.write_bytes(p.read_bytes()[:-30])
        with self.assertRaisesRegex(ValueError, 'section table'):
            module_info(p)

    def test_missing_ordered_module_rejected(self):
        (self.stage / 'consumer.ko').unlink()
        with self.assertRaisesRegex(ValueError, 'ordered module missing'):
            verify(self.kernel, self.stage)

    def test_outside_ordered_module_rejected(self):
        (self.stage / 'modules.order').write_text(str(self.kernel / 'provider.o') + '\n')
        with self.assertRaisesRegex(ValueError, 'outside build'):
            verify(self.kernel, self.stage)


if __name__ == '__main__':
    unittest.main()
