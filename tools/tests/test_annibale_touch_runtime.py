# SPDX-License-Identifier: GPL-2.0-only
"""Compile the actual changed touch functions against failure-injection mocks."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


class TouchRuntimeTests(unittest.TestCase):
    def test_panel_lifecycle_and_power_supply_references(self):
        repo = Path(__file__).resolve().parents[2]
        source = (repo / 'xiaomi/touch/annibale/xiaomi/xiaomi_touch_core.c').read_text()
        names = ('xiaomi_register_panel_notifier_work', 'schedule_resume_suspend_work',
                 'xiaomi_register_panel_notifier', 'xiaomi_unregister_panel_notifier',
                 'xiaomi_supply_online', 'xiaomi_get_charging_status')
        functions = []
        for name in names:
            # Functions are at column zero; the closing brace is too. This uses
            # real driver bodies, never a separately maintained reimplementation.
            match = re.search(r'^(?:static )?(?:void|bool|int) ' + name + r'\(', source, re.M)
            self.assertIsNotNone(match, name)
            start = match.start()
            end = source.index('\n}', start) + 2
            functions.append(source[start:end])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'touch_under_test.inc').write_text('\n'.join(functions) + '\n')
            binary = root / 'touch_runtime'
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Werror', '-fsanitize=undefined',
                            '-I', str(root), str(Path(__file__).with_name('touch_runtime.c')),
                            '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
