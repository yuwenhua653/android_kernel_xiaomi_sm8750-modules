# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_annibale_loader import (MARKER, check_consumer, export_policy,
                                   signature, soft_dependencies)


class LoaderMetadata(unittest.TestCase):
    def test_namespace_enforcement(self):
        providers = {'foo': {'owner': 'p', 'gpl_only': False, 'namespace': 'PRIVATE'}}
        self.assertTrue(check_consumer('c', {}, ['foo'], providers, set()))
        self.assertFalse(check_consumer('c', {'import_ns': ['PRIVATE']}, ['foo'], providers, set()))

    def test_gpl_taint_and_missing_provider(self):
        providers = {'foo': {'owner': 'p', 'gpl_only': True, 'namespace': ''}}
        self.assertTrue(check_consumer('c', {}, ['foo'], providers, {'c'}))
        self.assertFalse(check_consumer('c', {}, ['foo'], providers, set()))
        self.assertTrue(check_consumer('c', {}, ['missing'], providers, set()))

    def test_export_class_and_namespace_use_defining_symbols(self):
        symbols = {'__ksymtab_foo': (1, 0), '__kstrtabns_foo': (2, 1)}
        parts = {'strings': b'\0NS\0'}
        policy = export_policy(symbols, ['', '__ksymtab_gpl', 'strings'], parts)
        self.assertEqual(policy['foo'], {'gpl_only': True, 'namespace': 'NS'})
        for labels in (['', 'unexpected', 'strings'], ['', '__ksymtab', 'strings']):
            if labels[1] == 'unexpected':
                with self.assertRaises(ValueError):
                    export_policy(symbols, labels, parts)
        with self.assertRaises(ValueError):
            export_policy({'__ksymtab_foo': (1, 0)}, ['', '__ksymtab'], {})

    def test_softdep_preserves_pre_and_post_and_rejects_ambiguity(self):
        self.assertEqual(soft_dependencies(['pre: a-b c post: d']),
                         {'pre': ['a_b', 'c'], 'post': ['d']})
        for value in ('a', 'pre: ../x', 'other: a'):
            with self.assertRaises(ValueError):
                soft_dependencies([value])

    def test_signature_truncation_bounds_and_reserved_bytes(self):
        self.assertEqual(signature(b'ELF'), {'status': 'unsigned'})
        with self.assertRaises(ValueError):
            signature(MARKER)
        for size, extra in ((0, 0), (1000, 0), (3, 1)):
            raw = b'ELFxxx' + struct.pack('>8BI', extra, 0, 2, 0, 0, 0, 0, 0, size) + MARKER
            with self.assertRaises(ValueError):
                signature(raw)

    def test_invalid_pkcs7_is_not_called_signed(self):
        raw = b'ELFxxx' + struct.pack('>8BI', 0, 0, 2, 0, 0, 0, 0, 0, 3) + MARKER
        with self.assertRaisesRegex(ValueError, 'unparseable'):
            signature(raw)


if __name__ == '__main__':
    unittest.main()
