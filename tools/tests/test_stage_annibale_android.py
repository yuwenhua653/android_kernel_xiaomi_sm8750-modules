# SPDX-License-Identifier: GPL-2.0-only
"""Exercise generated shell failure semantics and Android dependency ownership."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stage_annibale_android import loader, validate_dep, write_make_example


class NativeLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = self.root / 'calls'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.sys = self.root / 'sys/module'
        self.sys.mkdir(parents=True)
        (self.sys / 'boot_core').mkdir()
        self.dirs = {}
        for partition, names in (('system_dlkm', ['system-base.ko']),
                                 ('vendor_dlkm', ['codec.ko', 'machine.ko'])):
            directory = self.root / partition / 'lib/modules'
            directory.mkdir(parents=True)
            (directory / 'modules.load').write_text('\n'.join(names) + '\n')
            (directory / 'modules.dep').write_text('present\n')
            for name in names:
                (directory / name).touch()
            self.dirs[partition] = directory
        self.command('uname', 'echo 6.6.test\n')
        self.command('setprop', 'echo "property $*" >> "$CALLS"\n[ "${FAIL_PROPERTY:-}" != "$2" ]\n')
        self.command('modprobe', '''for module do :; done
echo "module $module" >> "$CALLS"
[ "${FAIL_MODULE:-}" != "$module" ] || exit 1
[ "${FAKE_SUCCESS:-}" != "$module" ] || exit 0
name=$(printf '%s' "${module%.ko}" | tr '-' '_')
mkdir -p "$FAKE_SYS/$name"
''')
        (self.bin / 'tr').symlink_to('/usr/bin/tr')

    def command(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/sh\n' + body)
        path.chmod(0o755)

    def run_loader(self, mode='vendor', **environment):
        # Remap only the test copy; production scripts have no environment override.
        text = loader(mode, '6.6.test', ['boot_core'])
        for partition, directory in self.dirs.items():
            text = text.replace('/' + partition + '/lib/modules', str(directory))
        text = text.replace('/vendor/bin/', str(self.bin) + '/').replace('/sys/module', str(self.sys))
        script = self.root / 'loader.sh'
        script.write_text(text)
        env = {**os.environ, 'CALLS': str(self.log), 'FAKE_SYS': str(self.sys), **environment}
        result = subprocess.run(['/bin/sh', str(script)], env=env, capture_output=True, text=True)
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return result, calls

    def test_success_is_ordered_and_ready_last(self):
        result, calls = self.run_loader()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['property vendor.all.modules.ready 0', 'module system-base.ko',
                                 'module codec.ko', 'module machine.ko', 'property vendor.all.modules.ready 1'])

    def test_system_service_never_sets_vendor_ready(self):
        result, calls = self.run_loader('system')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['module system-base.ko'])

    def test_system_failure_prevents_vendor_loading(self):
        result, calls = self.run_loader(FAIL_MODULE='system-base.ko')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, ['property vendor.all.modules.ready 0', 'module system-base.ko'])

    def test_late_failure_does_not_set_ready(self):
        result, calls = self.run_loader(FAIL_MODULE='machine.ko')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('property vendor.all.modules.ready 1', calls)

    def test_success_without_insertion_is_rejected(self):
        result, calls = self.run_loader(FAKE_SUCCESS='codec.ko')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('module machine.ko', calls)

    def test_wrong_release_stops_before_insertion(self):
        self.command('uname', 'echo 6.6.other\n')
        result, calls = self.run_loader()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, ['property vendor.all.modules.ready 0'])

    def test_missing_first_stage_provider_stops_before_insertion(self):
        (self.sys / 'boot_core').rmdir()
        result, calls = self.run_loader()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, ['property vendor.all.modules.ready 0'])

    def test_bad_list_validated_before_partition_load(self):
        for invalid in ('../bad.ko', '-bad.ko', 'bad name.ko', 'bad', '', 'bad;command.ko'):
            with self.subTest(invalid=invalid):
                self.log.unlink(missing_ok=True)
                (self.dirs['vendor_dlkm'] / 'modules.load').write_text('codec.ko\n' + invalid + '\n')
                result, calls = self.run_loader()
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('module codec.ko', calls)

    def test_missing_list_or_index_fails(self):
        for filename in ('modules.load', 'modules.dep'):
            with self.subTest(filename=filename):
                path = self.dirs['system_dlkm'] / filename
                saved = path.read_text()
                path.unlink()
                result, calls = self.run_loader()
                self.assertNotEqual(result.returncode, 0)
                path.write_text(saved)

    def test_property_failure_is_not_success(self):
        for value in ('0', '1'):
            with self.subTest(value=value):
                result, calls = self.run_loader(FAIL_PROPERTY=value)
                self.assertNotEqual(result.returncode, 0)


class DepmodTests(unittest.TestCase):
    def setUp(self):
        self.entries = [{'name': 'base', 'partition': 'system_dlkm', 'source': '/build/base.ko'},
                        {'name': 'codec', 'partition': 'vendor_dlkm', 'source': '/build/codec.ko'}]
        self.verification = {'modules': {'base': {'depends': []}, 'codec': {'depends': ['base', 'boot_core']}}}
        self.good = '/system/lib/modules/base.ko:\n/vendor/lib/modules/codec.ko: /system/lib/modules/base.ko\n'

    def test_android_mount_aliases_and_preloaded_provider(self):
        checked = validate_dep(self.good, self.entries, self.verification)
        self.assertEqual(checked['dependency_references'], 1)

    def test_invalid_or_missing_dependencies_rejected(self):
        for text in (self.good.replace('/system/lib', '/system_dlkm/lib'),
                     self.good.replace(': /system/lib/modules/base.ko', ':'),
                     self.good + '/vendor/lib/modules/other.ko:\n',
                     self.good + '/system/lib/modules/base.ko:\n',
                     self.good.replace('/system/lib/modules/base.ko:', '/system/lib/modules/../base.ko:')):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    validate_dep(text, self.entries, self.verification)

    def test_make_example_is_parseable_and_rejects_previous_owners(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            entries = [dict(e, destination=e['partition'] + '/lib/modules/' + Path(e['source']).name) for e in self.entries]
            entries.insert(0, {'partition': 'vendor_boot', 'destination': 'vendor_boot/lib/modules/core.ko'})
            write_make_example(path, {'entries': entries})
            makefile = path / 'BoardConfig.modules.mk.example'
            with makefile.open('a') as stream:
                stream.write('\nall:\n\t@echo $(BOARD_VENDOR_KERNEL_MODULES)\n')
            command = ['make', '-f', str(makefile), 'ANNIBALE_MODULE_STAGE=stage']
            good = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertIn('stage/vendor_dlkm/lib/modules/codec.ko', good.stdout)
            bad = subprocess.run(command + ['BOARD_VENDOR_KERNEL_MODULES=stock.ko'], capture_output=True)
            self.assertNotEqual(bad.returncode, 0)


if __name__ == '__main__':
    unittest.main()
