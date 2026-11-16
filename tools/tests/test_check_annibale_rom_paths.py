# SPDX-License-Identifier: GPL-2.0-only
"""Both ROM paths must be checked; neither can conceal the other's failure."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_annibale_rom_paths as dual


class RomPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_check(self, native_error=None, stock_status='no_detected_abi_blocker'):
        native = {'modules': {'source_only': {}, 'shared': {}}}
        stock = {'status': stock_status,
                 'modules': [{'name': 'stock_only'}, {'name': 'shared'}]}
        with patch.object(dual, 'check_build_inputs', return_value={}), \
             patch.object(dual, 'verify', return_value=native, side_effect=native_error) as v, \
             patch.object(dual, 'audit', return_value=stock) as a:
            report = dual.check(self.root, self.root, self.root)
            v.assert_called_once()
            a.assert_called_once()
            return report

    def test_stock_pass_does_not_hide_native_failure(self):
        r = self.run_check(native_error=ValueError('missing source dependency'))
        self.assertEqual(r['status'], 'blocked')
        self.assertIn('missing source dependency', r['native_source_modules']['error'])

    def test_native_pass_does_not_hide_stock_failure(self):
        self.assertEqual(self.run_check(stock_status='blocked')['status'], 'blocked')

    def test_unresolved_variants_and_unknown_status_fail_closed(self):
        self.assertEqual(self.run_check(stock_status='incomplete_inventory')['status'],
                         'incomplete_inventory')
        self.assertEqual(self.run_check(stock_status='unexpected')['status'], 'blocked')

    def test_both_static_passes_do_not_claim_boot_or_allow_mixing(self):
        r = self.run_check()
        self.assertEqual(r['status'], 'static_checks_passed')
        self.assertIs(r['boot_compatibility_verified'], False)
        self.assertEqual(r['module_ownership']['names_present_in_both_profiles'], ['shared'])
        self.assertEqual(r['module_ownership']['stock_names_without_built_source_counterpart'],
                         ['stock_only'])

    def test_stale_image_and_missing_provenance_fail(self):
        record = {'objects_only': False, 'returncode': 0, 'make_returncode': 0,
                  'verification_status': 'passed', 'kernel_inputs_unchanged': True,
                  'kernel_inputs': {}}
        for name in dual.KERNEL_INPUTS:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(name.encode())
            record['kernel_inputs'][str(p)] = dual.digest(p)
        (self.root / 'build.json').write_text(json.dumps(record))
        self.assertEqual(len(dual.check_build_inputs(self.root, self.root)), 7)
        (self.root / 'arch/arm64/boot/Image').write_bytes(b'stale')
        with self.assertRaisesRegex(ValueError, 'stale/unrecorded.*Image'):
            dual.check_build_inputs(self.root, self.root)
        record['objects_only'] = True
        (self.root / 'build.json').write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'complete build record'):
            dual.check_build_inputs(self.root, self.root)

    def test_broken_inputs_still_audit_stock(self):
        with patch.object(dual, 'check_build_inputs', side_effect=ValueError('stale Image')), \
             patch.object(dual, 'verify') as verify, \
             patch.object(dual, 'audit', side_effect=OSError('missing inventory')) as audit:
            r = dual.check(self.root, self.root, self.root)
            self.assertEqual(r['status'], 'blocked')
            verify.assert_not_called()
            audit.assert_called_once()
            self.assertEqual(r['hyperos_stock_modules']['status'], 'blocked')


if __name__ == '__main__':
    unittest.main()
