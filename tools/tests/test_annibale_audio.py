"""Exercise real C binding with failed/deferred providers and devres cleanup."""
from pathlib import Path
import subprocess
import tempfile
import unittest


class AudioBindingTests(unittest.TestCase):
    def test_real_dmic_and_sysfs_lifecycle(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('linux/device.h', 'linux/of.h', 'linux/slab.h',
                         'linux/kobject.h', 'linux/sysfs.h', 'sound/soc.h',
                         'asoc/msm-cdc-pinctrl.h'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            binary = root / 'audio_runtime'
            subprocess.run([
                'cc', '-std=c11', '-Wall', '-Werror', '-fsanitize=undefined',
                '-I', str(root), '-I', str(repo / 'qcom/opensource/audio-kernel/asoc'),
                str(Path(__file__).with_name('audio_runtime.c')), '-o', str(binary)
            ], check=True)
            subprocess.run([str(binary)], check=True)

    def test_real_binding_probe_and_cleanup(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('linux/device.h', 'linux/of.h', 'linux/slab.h', 'sound/soc.h'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            binary = root / 'audio_binding'
            subprocess.run([
                'cc', '-std=c11', '-Wall', '-Werror', '-fsanitize=undefined',
                '-I', str(root), '-I', str(repo / 'qcom/opensource/audio-kernel/asoc'),
                str(Path(__file__).with_name('audio_binding.c')), '-o', str(binary)
            ], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
