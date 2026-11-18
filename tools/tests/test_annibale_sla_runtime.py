# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual SLA functions with host lifetime and packet fault injection.

These tests do not emulate kernel MM/procfs, lockdep or device userspace.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


class SlaRuntimeTests(unittest.TestCase):
    def run_fixture(self, fixture, names, declarations=()):
        repo = Path(__file__).resolve().parents[2]
        driver = repo / 'xiaomi/sla/annibale'
        source = (driver / 'stats.c').read_text()
        pieces = []
        for name in declarations:
            start = source.index('struct ' + name + ' {')
            pieces.append(source[start:source.index('\n};', start) + 3])
        for name in names:
            match = re.search(r'^static [^\n;]*\b' + name + r'\([^;]*?\n\{', source, re.M)
            self.assertIsNotNone(match, name)
            pieces.append(source[match.start():source.index('\n}', match.start()) + 2])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'linux').mkdir()
            (root / 'linux/kref.h').write_text('/* refcount mock supplied by fixture */\n')
            (root / 'sla_under_test.inc').write_text('\n\n'.join(pieces) + '\n')
            binary = root / 'test'
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Werror', '-fsanitize=undefined', '-fno-sanitize-recover=all',
                            '-I', str(root), '-I', str(driver),
                            str(Path(__file__).with_name(fixture)), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=20)

    def test_file_mapping_disable_and_init_failures(self):
        self.run_fixture('sla_lifetime.c', (
            'sla_iface_release', 'stats_vma_open', 'stats_vma_close',
            'stats_map', 'stats_open', 'stats_release', 'sla_stats_data_init',
            'sla_find_interface', 'sla_interface_start', 'sla_stats_disable',
            'sla_stats_enable', 'sla_stats_command', 'config_file_write'))

    def test_packet_headers_and_truncation(self):
        self.run_fixture('sla_packet.c', ('sla_parse_packet',), ('sla_packet',))

    def test_voip_partial_read_snapshot(self):
        self.run_fixture('sla_voip.c', ('sla_voip_file_open', 'sla_voip_file_release',
                                      'sla_voip_file_read'), ('sla_voip_reader',))


if __name__ == '__main__':
    unittest.main()
