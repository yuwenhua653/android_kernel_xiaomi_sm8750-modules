# SPDX-License-Identifier: GPL-2.0-only
from copy import deepcopy
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_plan_annibale_modules import module
from plan_annibale_modules import resolve
from annibale_power import ROOTS, SUPPLIERS, BUILTINS, PROFILE, CONFIGS, check_config
from check_annibale_power_dt import COMPAT, inspect


class PowerPlanTests(unittest.TestCase):
    def setUp(self):
        self.names = ROOTS | set.union(*SUPPLIERS.values()) - BUILTINS
        self.v = {'release': 'test', 'modules': {n: module(n) for n in self.names}}
        self.p = {'schema_version': 1, 'profile': 'native-source-qualification',
                  'boot_mode': 'normal', 'complete_device': False, 'power_profile': PROFILE,
                  'roots': sorted(ROOTS), 'board_requires': {n: {'modules': sorted(s), 'reason': 'test'} for n, s in SUPPLIERS.items()},
                  'ownership': [{'name': n, 'partition': 'vendor_dlkm', 'source': 'source-build', 'reason': 'test'} for n in self.names]}

    def test_gpu_and_cpu_provider_order(self):
        plan = resolve(self.v, self.p, BUILTINS)
        names = plan['partitions']['vendor_dlkm']
        self.assertLess(names.index('msm_kgsl'), names.index('qti_devfreq_cdev'))
        self.assertLess(names.index('qcom_cpucp'), names.index('qcom_cpufreq_thermal'))
        self.assertLess(names.index('qti_thermal_vendor_hooks'), names.index('qti_cpufreq_cdev'))

    def test_loaded_gpu_does_not_replace_explicit_order(self):
        self.p['roots'].append('msm_kgsl')
        self.p['board_requires']['qti_devfreq_cdev']['modules'].remove('msm_kgsl')
        with self.assertRaisesRegex(ValueError, 'power suppliers: qti_devfreq_cdev'):
            resolve(self.v, self.p, BUILTINS)

    def test_missing_lpm(self):
        self.p['roots'].remove('qcom_lpm')
        with self.assertRaisesRegex(ValueError, 'power driver: qcom_lpm'):
            resolve(self.v, self.p, BUILTINS)

    def test_scmi_core_must_be_builtin(self):
        with self.assertRaisesRegex(ValueError, 'built-in SCMI'):
            resolve(self.v, self.p, BUILTINS - {'scmi_core'})

    def test_psci_config_must_be_builtin(self):
        config = '\n'.join('CONFIG_' + n + '=y' for n in CONFIGS)
        check_config(self.p, config)
        with self.assertRaisesRegex(ValueError, 'ARM_PSCI_CPUIDLE_DOMAIN'):
            check_config(self.p, config.replace('CONFIG_ARM_PSCI_CPUIDLE_DOMAIN=y', 'CONFIG_ARM_PSCI_CPUIDLE_DOMAIN=m'))


def pack(*values):
    return struct.pack('>' + 'I' * len(values), *values)


def cells(value):
    return list(struct.unpack('>' + 'I' * (len(value) // 4), value))


class PowerDtTests(unittest.TestCase):
    def setUp(self):
        nodes = {'/': {}, '/soc': {}, '/supplier': {'phandle': pack(1), '#mbox-cells': pack(1),
                 '#power-domain-cells': pack(0), '#interconnect-cells': pack(1)},
                 '/scmi': {'phandle': pack(2), '#clock-cells': pack(1), 'reg': pack(0x13)}}
        self.paths = {}
        for i, (compat, count) in enumerate(COMPAT.items()):
            for j in range(count):
                path = f'/soc/n{i}_{j}'
                self.paths.setdefault(compat, []).append(path)
                nodes[path] = {'compatible': compat.encode() + b'\0'}
        def props(c):
            return nodes[self.paths[c][0]]
        ocp = props('qcom,regulator-ocp-notifier')
        ocp.update({f'r{i}-supply': pack(1) for i in range(69)})
        ocp['nvmem-cells'] = pack(1, 1)
        props('qcom,cpufreq-thermal').update({'mboxes': pack(1, 5, 1, 6), 'qcom,policy-cpus': pack(0, 6)})
        for path in self.paths['qcom,lpm-cluster-dev']:
            nodes[path]['power-domains'] = pack(1)
        props('qcom,ddr-cooling-device')['interconnects'] = pack(1, 3, 1, 513)
        props('qcom,devfreq-cdev')['qcom,devfreq'] = pack(1)
        for i in range(8):
            nodes[f'/cpu{i}'] = {'device_type': b'cpu\0', 'clocks': pack(2, 0 if i < 6 else 1)}
        self.tree = SimpleNamespace(nodes=nodes)

    def test_typed_numeric_arguments_are_not_phandles(self):
        report = inspect(self.tree, cells)
        self.assertEqual(report['cpus'], 8)

    def test_disabled_supplier(self):
        self.tree.nodes['/supplier']['status'] = b'disabled\0'
        with self.assertRaisesRegex(ValueError, 'disabled provider'):
            inspect(self.tree, cells)

    def test_disabled_ancestor(self):
        self.tree.nodes['/soc']['status'] = b'disabled\0'
        with self.assertRaisesRegex(ValueError, 'active nodes'):
            inspect(self.tree, cells)

    def test_truncated_mailbox(self):
        path = self.paths['qcom,cpufreq-thermal'][0]
        self.tree.nodes[path]['mboxes'] = pack(1, 5, 1)
        with self.assertRaisesRegex(ValueError, 'truncated provider'):
            inspect(self.tree, cells)

    def test_clock_protocol_is_not_performance_protocol(self):
        self.tree.nodes['/scmi']['reg'] = pack(0x14)
        with self.assertRaisesRegex(ValueError, 'protocol 0x13'):
            inspect(self.tree, cells)
