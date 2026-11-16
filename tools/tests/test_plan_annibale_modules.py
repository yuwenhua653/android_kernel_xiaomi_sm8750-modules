# SPDX-License-Identifier: GPL-2.0-only
"""Reject unavailable boot-stage providers, stale bytes and mixed owners."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plan_annibale_modules import resolve, softdeps, stage_plan


def module(name, depends=(), softdep=()):
    return {'path': f'/build/{name.replace("_", "-")}.ko', 'sha256': '0' * 64,
            'depends': list(depends), 'softdep': list(softdep), 'firmware': []}


class PartitionPlanTests(unittest.TestCase):
    def setUp(self):
        self.v = {'release': '6.6.test', 'modules': {
            'core': module('core'), 'radio': module('radio', ['core']),
            'phy': module('phy'), 'monitor': module('monitor')}}
        self.p = {'schema_version': 1, 'profile': 'native-source-qualification',
                  'boot_mode': 'normal', 'complete_device': False, 'roots': ['radio'],
                  'ownership': [self.owner('core', 'vendor_boot'), self.owner('radio')]}

    @staticmethod
    def owner(name, partition='vendor_dlkm'):
        return {'name': name, 'partition': partition, 'source': 'source-build', 'reason': 'fixture review'}

    def run_plan(self, builtins=()):
        return resolve(self.v, self.p, set(builtins))

    def test_hard_dependencies_cross_valid_stage(self):
        r = self.run_plan()
        self.assertEqual(r['selected_module_count'], 2)
        self.assertEqual(r['partitions']['vendor_boot'], ['core'])
        self.assertFalse(r['flashable'])
        self.assertFalse(r['complete_device'])

    def audio_fixture(self, variant):
        names = ['machine_dlkm', 'tfa98xx_dlkm'] if variant == 'tfa' else [
            'machine_dlkm', 'sia91xx_dlkm', 'sia91xx_tuning_dlkm']
        self.v['modules'].update({n: module(n) for n in names})
        self.p['roots'] += ['machine_dlkm']
        self.p['audio_variant'] = variant
        self.p['ownership'] += [self.owner(n) for n in names]
        self.p['board_requires'] = {'machine_dlkm': {
            'modules': names[1:], 'reason': 'OF codec providers, not ELF imports'}}

    def test_audio_families_are_individually_ordered(self):
        for variant in ('tfa', 'sia'):
            with self.subTest(variant=variant):
                self.setUp()
                self.audio_fixture(variant)
                report = self.run_plan()
                self.assertEqual(report['audio_variant'], variant)
                order = report['partitions']['vendor_dlkm']
                for name in self.p['board_requires']['machine_dlkm']['modules']:
                    self.assertLess(order.index(name), order.index('machine_dlkm'))

    def test_audio_plan_rejects_implicit_or_unknown_family(self):
        for variant in (None, '', 'auto', 'tfa sia', ['tfa']):
            self.p['audio_variant'] = variant
            with self.assertRaisesRegex(ValueError, 'explicitly select'):
                self.run_plan()

    def test_audio_plan_rejects_opposite_family_in_transitive_closure(self):
        self.audio_fixture('tfa')
        self.v['modules']['sia91xx_dlkm'] = module('sia91xx_dlkm')
        self.v['modules']['radio']['softdep'] = ['pre: sia91xx_dlkm']
        with self.assertRaisesRegex(ValueError, 'mixes smartpa'):
            self.run_plan()

    def test_audio_plan_requires_sia_tuning_and_runtime_order(self):
        self.audio_fixture('sia')
        self.p['board_requires']['machine_dlkm']['modules'].remove('sia91xx_tuning_dlkm')
        with self.assertRaisesRegex(ValueError, 'missing the selected'):
            self.run_plan()
        self.p['roots'] += ['sia91xx_tuning_dlkm']
        with self.assertRaisesRegex(ValueError, 'board dependencies'):
            self.run_plan()

    def test_soft_pre_and_post_are_both_selected_and_ordered(self):
        self.v['modules']['radio']['softdep'] = ['pre: phy post: monitor']
        self.p['ownership'] += [self.owner('phy'), self.owner('monitor')]
        self.assertEqual(self.run_plan()['partitions']['vendor_dlkm'], ['phy', 'radio', 'monitor'])

    def test_missing_soft_dependency_is_not_silently_ignored(self):
        self.v['modules']['radio']['softdep'] = ['pre: legacy-provider']
        with self.assertRaisesRegex(ValueError, 'missing soft-pre provider legacy_provider'):
            self.run_plan()

    def test_builtin_provider_satisfies_pre(self):
        self.v['modules']['radio']['softdep'] = ['pre: integrated']
        self.assertEqual(self.run_plan(['integrated'])['builtin_dependencies'], ['integrated'])

    def test_builtin_cannot_be_post(self):
        self.v['modules']['radio']['softdep'] = ['post: integrated']
        with self.assertRaisesRegex(ValueError, 'cannot load after'):
            self.run_plan(['integrated'])

    def test_hard_soft_cycle(self):
        self.v['modules']['core']['softdep'] = ['pre: radio']
        self.p['ownership'][0]['partition'] = 'vendor_dlkm'
        with self.assertRaisesRegex(ValueError, 'dependency cycle'):
            self.run_plan()

    def test_early_boot_cannot_depend_on_late_partition(self):
        self.p['ownership'][0]['partition'] = 'vendor_dlkm'
        self.p['ownership'][1]['partition'] = 'vendor_boot'
        with self.assertRaisesRegex(ValueError, 'load-stage inversion'):
            self.run_plan()

    def test_system_partition_cannot_depend_on_vendor_dlkm(self):
        self.p['ownership'][0]['partition'] = 'vendor_dlkm'
        self.p['ownership'][1]['partition'] = 'system_dlkm'
        with self.assertRaisesRegex(ValueError, 'load-stage inversion'):
            self.run_plan()

    def test_ownership_must_cover_exact_closure(self):
        self.p['ownership'].pop(0)
        with self.assertRaisesRegex(ValueError, 'ownership must match'):
            self.run_plan()

    def test_no_unused_owned_modules(self):
        self.p['ownership'].append(self.owner('phy'))
        with self.assertRaisesRegex(ValueError, 'extra=.*phy'):
            self.run_plan()

    def test_same_name_stock_replacement_rejected(self):
        self.p['ownership'][0]['source'] = 'stock'
        with self.assertRaisesRegex(ValueError, 'stock modules are not accepted'):
            self.run_plan()

    def test_duplicate_normalized_name(self):
        self.v['modules']['some_core'] = self.v['modules'].pop('core')
        self.v['modules']['radio']['depends'] = ['some_core']
        self.p['ownership'][0]['name'] = 'some-core'
        self.p['ownership'].append(self.owner('some_core'))
        with self.assertRaisesRegex(ValueError, 'duplicate normalized owner'):
            self.run_plan()

    def test_recovery_and_complete_device_claim_rejected(self):
        for key, value in [('boot_mode', 'recovery'), ('complete_device', True), ('profile', 'stock')]:
            with self.subTest(key=key):
                p = deepcopy(self.p)
                p[key] = value
                with self.assertRaises(ValueError):
                    resolve(self.v, p, set())

    def test_board_provider_is_not_lost(self):
        self.p['board_requires'] = {'radio': {'modules': ['phy'], 'reason': 'DT supply'}}
        self.p['ownership'].append(self.owner('phy'))
        self.assertEqual(self.run_plan()['partitions']['vendor_dlkm'], ['phy', 'radio'])

    def test_invalid_softdep_syntax(self):
        for line in ['', 'phy', 'pre:', 'pre: post: phy', 'pre: ../phy', 'pre: phy post:']:
            with self.subTest(line=line), self.assertRaises(ValueError):
                softdeps([line])

    def test_partition_order_beats_unrelated_ready_node(self):
        self.p['roots'].append('monitor')
        self.p['ownership'].append(self.owner('monitor', 'system_dlkm'))
        self.assertEqual([e['name'] for e in self.run_plan()['entries']], ['core', 'monitor', 'radio'])

    def test_staging_checks_bytes_and_preserves_basename(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            for name, meta in self.v['modules'].items():
                p = root / f'{name}-driver.ko'
                p.write_bytes(name.encode())
                meta.update(path=str(p), sha256=hashlib.sha256(name.encode()).hexdigest())
            r = self.run_plan()
            dst = root / 'staged'
            stage_plan(r, dst)
            self.assertEqual((dst / 'vendor_boot/lib/modules/modules.load.candidate').read_text(), 'core-driver.ko\n')
            self.assertEqual((dst / 'vendor_dlkm/lib/modules/radio-driver.ko').read_bytes(), b'radio')
            self.assertTrue((dst / 'manifest.json').is_file())
            with self.assertRaisesRegex(ValueError, 'must not exist'):
                stage_plan(r, dst)
            Path(self.v['modules']['radio']['path']).write_bytes(b'stale')
            with self.assertRaisesRegex(ValueError, 'changed after verification'):
                stage_plan(r, root / 'bad-stage')
            self.assertFalse((root / 'bad-stage').exists())
            self.assertFalse(list(root.glob('bad-stage-*')))


if __name__ == '__main__':
    unittest.main()
