#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fault-injected stock inventories must not be called HyperOS compatible."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_annibale_stock import audit, compare, exports, magic_flags


def module(path, name='consumer', imports=None, provided=None,
           release='6.6.stock', depends='', flags='SMP modversions aarch64'):
    imports = imports if imports is not None else {'module_layout': 0x1234}
    provided = provided or {}
    labels = ['', '.shstrtab', '.modinfo', '__versions', '.strtab',
              '__ksymtab', '__kcrctab', '.symtab']
    names = ('\0'.join(labels) + '\0').encode()
    strings = b'\0'; symtab = bytes(24)
    for i, symbol in enumerate(provided):
        for prefix, index, value in [('__ksymtab_', 5, i * 12), ('__crc_', 6, i * 4)]:
            pos = len(strings); strings += (prefix + symbol + '\0').encode()
            symtab += struct.pack('<IBBHQQ', pos, 0, 0, index, value, 0)
    info = f'name={name}\0vermagic={release} {flags}\0depends={depends}\0'.encode()
    versions = b''.join(struct.pack('<Q56s', crc, n.encode()) for n, crc in imports.items())
    data = [b'', names, info, versions, strings, bytes(12 * len(provided)),
            b''.join(struct.pack('<I', c) for c in provided.values()), symtab]
    pos = 64; offsets = []
    for d in data: offsets.append(pos); pos += len(d)
    header = struct.pack('<16sHHIQQQIHHHHHH', b'\x7fELF\x02\x01\x01' + bytes(9),
                         1, 183, 1, 0, 0, pos, 0, 64, 0, 0, 64, len(labels), 1)
    tables = b''
    for i, label in enumerate(labels):
        tables += struct.pack('<IIQQQQIIQQ', names.index(label.encode()) if label else 0,
                              2 if i == 7 else 3 if i in (1, 4) else 1,
                              0, 0, offsets[i], len(data[i]), 4 if i == 7 else 0,
                              0, 1, 24 if i == 7 else 0)
    path.write_bytes(header + b''.join(data) + tables)


class StockAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.stock = self.root / 'stock'; self.stock.mkdir()
        self.kernel = self.root / 'kernel'; (self.kernel / 'include/config').mkdir(parents=True)
        (self.kernel / '.config').write_text('CONFIG_MODVERSIONS=y\n')
        (self.kernel / 'include/config/kernel.release').write_text('6.6.target\n')
        (self.kernel / 'modules.order').write_text('target.o\n')
        (self.kernel / 'Module.symvers').write_text('0x1234\tmodule_layout\tvmlinux\tEXPORT_SYMBOL\n')
        module(self.kernel / 'target.ko', 'target', release='6.6.target')
        module(self.stock / 'consumer.ko')

    def run_audit(self):
        return audit(self.stock, self.kernel)

    def test_release_difference_not_itself_a_blocker(self):
        r = self.run_audit()
        self.assertEqual(r['status'], 'no_detected_abi_blocker')
        self.assertEqual(r['modules'][0]['kernel_imports_checked'], 1)
        self.assertIn('HALs', ' '.join(r['unverified']))

    def test_reads_export_crc_not_consumer_guess(self):
        module(self.stock / 'provider.ko', 'provider', provided={'real_api': 0xaabbccdd})
        self.assertEqual(exports(self.stock / 'provider.ko'), {'real_api': 0xaabbccdd})
        module(self.stock / 'consumer.ko', imports={'module_layout': 0x1234, 'real_api': 0xaabbccdd}, depends='provider')
        self.assertEqual(self.run_audit()['status'], 'no_detected_abi_blocker')
        module(self.stock / 'provider.ko', 'provider', provided={'real_api': 0x9999})
        self.assertEqual(self.run_audit()['counts']['stock_provider_crc_mismatches'], 1)

    def test_kernel_crc_beats_retained_provider(self):
        r = compare({'module_layout': 0x1234}, {'module_layout': [('bad', 0x1234)]},
                    {'module_layout': (0xabcd, 'vmlinux')})
        self.assertIn('module_layout', r['kernel_crc_mismatches'])

    def test_missing_symbols_dependencies_and_flags(self):
        module(self.stock / 'consumer.ko', imports={'module_layout': 0x9999, 'lost': 1},
               depends='lost_provider', flags='SMP modversions wrongarch')
        r = self.run_audit()
        self.assertEqual(r['status'], 'blocked')
        self.assertEqual(set(r['modules'][0]['blockers']),
                         {'kernel_crc_mismatches', 'missing_symbols', 'missing_dependencies', 'vermagic_flags'})

    def test_builtin_export_collision(self):
        module(self.stock / 'consumer.ko', provided={'module_layout': 0x1234})
        self.assertEqual(self.run_audit()['counts']['duplicate_builtin_exports'], 1)

    def test_duplicate_files_and_conflicting_variants(self):
        (self.stock / 'duplicate.ko').write_bytes((self.stock / 'consumer.ko').read_bytes())
        self.assertEqual(self.run_audit()['unique_binaries'], 1)
        module(self.stock / 'variant.ko', release='6.6.other')
        r = self.run_audit()
        self.assertEqual(r['status'], 'incomplete_inventory')
        self.assertEqual(r['unique_names'], 1)
        self.assertEqual(r['unique_binaries'], 2)

    def test_bad_elf_and_missing_load_entry(self):
        (self.stock / 'bad.ko').write_bytes(b'broken')
        r = self.run_audit(); self.assertEqual(r['status'], 'blocked')
        self.assertEqual(len(r['invalid_modules']), 1)
        (self.stock / 'bad.ko').unlink()
        (self.stock / 'modules.load').write_text('# comment\n/lib/modules/missing.ko\nconsumer.ko\n')
        r = self.run_audit(); self.assertEqual(r['status'], 'incomplete_inventory')
        self.assertEqual(r['load_lists'][0]['missing_from_inventory'], ['/lib/modules/missing.ko'])

    def test_invalid_crc_location_rejected(self):
        path = self.stock / 'provider.ko'
        module(path, 'provider', provided={'api': 1})
        raw = bytearray(path.read_bytes())
        head = struct.unpack_from('<16sHHIQQQIHHHHHH', raw)
        symhdr = struct.unpack_from('<IIQQQQIIQQ', raw, head[6] + 7 * 64)
        struct.pack_into('<Q', raw, symhdr[4] + 48 + 8, 999999)
        path.write_bytes(raw)
        self.assertEqual(self.run_audit()['status'], 'blocked')

    def test_invalid_target_and_path_escape(self):
        (self.kernel / '.config').write_text('# CONFIG_MODVERSIONS is not set\n')
        with self.assertRaises(ValueError): self.run_audit()
        (self.kernel / '.config').write_text('CONFIG_MODVERSIONS=y\n')
        (self.stock / 'escape.ko').symlink_to(self.kernel / 'target.ko')
        with self.assertRaises(ValueError): self.run_audit()
        with self.assertRaises(ValueError): magic_flags('invalid')


if __name__ == '__main__':
    unittest.main()
