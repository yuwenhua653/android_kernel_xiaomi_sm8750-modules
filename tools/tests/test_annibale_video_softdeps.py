# SPDX-License-Identifier: GPL-2.0-only
"""Preprocess the actual declaration block for SUN and the retained legacy path."""
import json
from pathlib import Path
import subprocess
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'qcom/opensource/video-driver/driver/vidc/src/msm_vidc_probe.c'


class VideoSoftdepTests(unittest.TestCase):
    def declarations(self, sun):
        # The full SUN ELF is checked by the real same-build partition resolver.
        # This host test additionally exercises the unbuilt non-SUN branch.
        source = SOURCE.read_text().split('module_exit(msm_vidc_exit);', 1)[1]
        prefix = '#define IS_ENABLED(x) x\n#define MODULE_SOFTDEP(x) x\n#define MODULE_LICENSE(x)\n'
        if sun:
            prefix += '#define CONFIG_ARCH_SUN 1\n'
        result = subprocess.run(['gcc', '-E', '-P', '-x', 'c', '-'], input=prefix + source,
                                text=True, capture_output=True, check=True)
        lines = [line.strip().rstrip(';').strip() for line in result.stdout.splitlines()]
        return [json.loads(line) for line in lines if line]

    def test_sun_does_not_request_unavailable_legacy_pil(self):
        self.assertEqual(self.declarations(True), ['pre: msm-mmrm'])

    def test_other_platforms_retain_original_prerequisites(self):
        self.assertEqual(self.declarations(False), ['pre: subsys-pil-tz', 'pre: msm-mmrm'])
