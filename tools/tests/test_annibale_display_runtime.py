# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual P11 display functions with transport/parser failure injection."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


class DisplayRuntimeTests(unittest.TestCase):
    def test_rx_resources(self):
        repo = Path(__file__).resolve().parents[2]
        source = (repo / 'qcom/opensource/display-drivers/msm/dsi/dsi_display.c').read_text()
        functions = []
        for symbol in ('dsi_display_cmd_rx_locked', 'dsi_display_cmd_rx'):
            match = re.search(r'^static int ' + symbol + r'\([^;]+?\n\{', source, re.M)
            self.assertIsNotNone(match)
            functions.append(source[match.start():source.index('\n}', match.start()) + 2])
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / 'display_rx_under_test.inc').write_text('\n'.join(functions) + '\n')
            binary = root / 'display_rx'
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Werror', '-fsanitize=undefined',
                            '-I', str(root), str(Path(__file__).with_name('display_rx.c')),
                            '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_pb_quirks(self):
        repo = Path(__file__).resolve().parents[2]
        directory = repo / 'qcom/opensource/display-drivers/msm/dsi'
        names = {'dsi_panel.c': ('dsi_panel_annibale_invalidate',
                 'dsi_panel_annibale_backlight', 'dsi_panel_annibale_power_off_delay',
                 'dsi_panel_parse_annibale', 'dsi_panel_update_backlight'),
                 'dsi_display.c': ('dsi_display_annibale_read_build_id',)}
        functions = []
        for filename, symbols in names.items():
            source = (directory / filename).read_text()
            for symbol in symbols:
                match = re.search(r'^static (?:void|u32|int) ' + symbol + r'\([^;]+?\n\{', source, re.M)
                self.assertIsNotNone(match, symbol)
                end = source.index('\n}', match.start()) + 2
                functions.append(source[match.start():end])
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / 'display_under_test.inc').write_text('\n'.join(functions) + '\n')
            binary = root / 'display_runtime'
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Werror', '-fsanitize=undefined',
                            '-I', str(root), str(Path(__file__).with_name('display_runtime.c')),
                            '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
