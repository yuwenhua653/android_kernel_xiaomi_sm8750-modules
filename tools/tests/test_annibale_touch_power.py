# SPDX-License-Identifier: GPL-2.0-only
"""Compile actual touch power functions; inject failures and real host threads."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


class TouchPowerTests(unittest.TestCase):
    def run_fixture(self, fixture, symbols):
        repo = Path(__file__).resolve().parents[2]
        functions = []
        for filename, names in symbols.items():
            source = (repo / 'xiaomi/touch/annibale' / filename).read_text()
            for name in names:
                match = re.search(r'^(?:static )?(?:inline )?(?:void|bool|int) ' + name + r'\([^;]+?\n\{', source, re.M)
                self.assertIsNotNone(match, name)
                functions.append(source[match.start():source.index('\n}', match.start())+2])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'power_under_test.inc').write_text('\n'.join(functions)+'\n')
            binary = root / 'test'
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Werror', '-pthread', '-fsanitize=undefined',
                            '-I', str(root), str(Path(__file__).with_name(fixture)), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=20)

    def test_temperature_lifetime_and_supply_references(self):
        self.run_fixture('touch_temperature.c', {
            'xiaomi/xiaomi_touch.h': ('xiaomi_touch_temp_valid', 'xiaomi_touch_temp_degrees'),
            'xiaomi/xiaomi_touch_core.c': ('get_bms_temp_common', 'xiaomi_touch_temp_thread_func',
                'xiaomi_start_temperature_detection', 'xiaomi_stop_temperature_detection',
                'xiaomi_set_temperature_detection')})

    def test_charger_replay(self):
        self.run_fixture('touch_charger.c', {
            'goodix_9916k/goodix_ts_core.c': ('goodix_reset_charge_state', 'goodix_set_charge_state')})


if __name__ == '__main__':
    unittest.main()
