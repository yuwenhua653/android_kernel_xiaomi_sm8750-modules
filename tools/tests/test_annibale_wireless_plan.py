# SPDX-License-Identifier: GPL-2.0-only
"""A declared wireless profile must not silently regress to console-only UART."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_plan_annibale_modules import module
from plan_annibale_modules import resolve


class WirelessPlanTests(unittest.TestCase):
    def setUp(self):
        self.names = {'cnss2', 'btpower', 'btfm_slim_codec', 'slim_qcom_ngd_ctrl', 'pci_msm_drv',
                      'bam_dma', 'msm_geni_serial', 'gcc_sun', 'qnoc_sun', 'pinctrl_sun',
                      'pinctrl_spmi_gpio', 'nvmem_qcom_spmi_sdam', 'clk_rpmh', 'rpmh_regulator', 'qcom_aoss'}
        self.v = {'release': 'test', 'modules': {n: module(n) for n in self.names}}
        board = {'msm_geni_serial': ['qcom_geni_se', 'gcc_sun', 'qnoc_sun', 'pinctrl_sun'],
                 'btpower': ['pinctrl_spmi_gpio', 'nvmem_qcom_spmi_sdam', 'clk_rpmh', 'pinctrl_sun', 'rpmh_regulator', 'qcom_aoss'],
                 'slim_qcom_ngd_ctrl': ['bam_dma']}
        self.p = {'schema_version': 1, 'profile': 'native-source-qualification', 'boot_mode': 'normal',
                  'complete_device': False, 'wireless_profile': 'annibale-kiwi', 'roots': sorted(self.names),
                  'ownership': [{'name': n, 'partition': 'vendor_dlkm', 'source': 'source-build', 'reason': 'fixture'} for n in self.names],
                  'board_requires': {n: {'modules': deps, 'reason': 'fixture'} for n, deps in board.items()}}
        self.builtins = {'qcom_geni_se', 'qcom_geni_serial'}

    def run_plan(self):
        return resolve(self.v, self.p, self.builtins)

    def test_explicit_hs_uart_and_builtin_geni_provider(self):
        result = self.run_plan()
        self.assertEqual(result['wireless_profile'], 'annibale-kiwi')
        self.assertIn('qcom_geni_se', result['builtin_dependencies'])

    def test_builtin_console_is_not_a_replacement_for_hs_uart(self):
        self.p['roots'].remove('msm_geni_serial')
        self.p['roots'].append('qcom_geni_serial')
        self.p['ownership'] = [o for o in self.p['ownership'] if o['name'] != 'msm_geni_serial']
        del self.p['board_requires']['msm_geni_serial']
        with self.assertRaisesRegex(ValueError, 'missing Annibale wireless provider: msm_geni_serial'):
            self.run_plan()

    def test_loaded_nvmem_elsewhere_does_not_replace_bt_ordering(self):
        self.p['board_requires']['btpower']['modules'].remove('nvmem_qcom_spmi_sdam')
        with self.assertRaisesRegex(ValueError, 'wireless OF suppliers: btpower'):
            self.run_plan()

    def test_unknown_wireless_profile_rejected(self):
        self.p['wireless_profile'] = 'auto'
        with self.assertRaisesRegex(ValueError, 'explicitly select'):
            self.run_plan()
