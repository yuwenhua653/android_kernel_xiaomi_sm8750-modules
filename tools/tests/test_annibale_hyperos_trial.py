# SPDX-License-Identifier: GPL-2.0-only
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import trial_annibale_hyperos as t


def baseline():
    return {'properties': {'ro.product.device': 'annibale', 'ro.build.fingerprint': t.SYSTEM_FP,
                           'ro.vendor.build.fingerprint': t.VENDOR_FP,
                           'ro.build.version.incremental': 'OS4.0.6.0.XPKCNXM',
                           'ro.boot.flash.locked': '0', 'ro.boot.verifiedbootstate': 'orange',
                           'sys.boot_completed': '1', 'ro.boot.slot_suffix': '_b'},
            'queries': {'kernel_release': {'stdout': t.STOCK_RELEASE},
                        'selinux': {'stdout': 'Enforcing'}},
            'mounts': [{'mountpoint': '/data', 'filesystem': 'f2fs'}]}


def bootloader():
    return {'product': 'annibale', 'is-userspace': 'no', 'unlocked': 'yes',
            'current-slot': 'b', 'partition-size:boot_b': '0x6000000',
            'max-download-size': '0x10000000'}


class TrialGates(unittest.TestCase):
    def test_exact_firmware_and_userdata_gate(self):
        self.assertEqual(t.preflight(baseline()), 'b')
        for key, value in (('ro.product.device', 'myron'), ('ro.build.fingerprint', 'different'),
                           ('ro.vendor.build.fingerprint', 'OS4.0.0.18'),
                           ('ro.boot.flash.locked', '1'), ('sys.boot_completed', '0'),
                           ('ro.boot.slot_suffix', '_c')):
            report = baseline(); report['properties'][key] = value
            with self.assertRaises(ValueError):
                t.preflight(report)
        for fs in ('mifs', 'ext4', ''):
            report = baseline(); report['mounts'][0]['filesystem'] = fs
            with self.assertRaises(ValueError):
                t.preflight(report)

    def test_modified_kernel_and_permissive_baseline_stop(self):
        for key, value in (('kernel_release', t.TEST_RELEASE), ('selinux', 'Permissive')):
            report = baseline(); report['queries'][key]['stdout'] = value
            with self.assertRaises(ValueError):
                t.preflight(report)

    def test_bootloader_slot_lock_mode_and_size_guards(self):
        self.assertEqual(t.check_bootloader(bootloader(), 'b'), 'b')
        for key, value in (('product', 'myron'), ('is-userspace', 'yes'), ('unlocked', 'no'),
                           ('current-slot', 'a'), ('partition-size:boot_b', '0x1'),
                           ('max-download-size', '0x100'), ('max-download-size', 'invalid')):
            values = bootloader(); values[key] = value
            with self.assertRaises(ValueError):
                t.check_bootloader(values, 'b')

    def test_ambiguous_devices_or_variables_fail(self):
        self.assertEqual(t.parse_devices('SERIAL\tfastboot\n', 'fastboot'), 'SERIAL')
        for text in ('', 'A fastboot\nB fastboot', 'A unauthorized'):
            with self.assertRaises(ValueError):
                t.parse_devices(text, 'fastboot')
        self.assertEqual(t.parse_var('(bootloader) current-slot: b\nFinished.', 'current-slot'), 'b')
        self.assertEqual(t.parse_var('partition-size:boot_b: 0x6000000', 'partition-size:boot_b'), '0x6000000')
        for text in ('FAILED', 'current-slot: a\ncurrent-slot: b'):
            with self.assertRaises(ValueError):
                t.parse_var(text, 'current-slot')

    def test_bad_image_never_reaches_device(self):
        with tempfile.TemporaryDirectory() as d, patch.object(t, 'one_device') as devices:
            p = Path(d) / 'boot.img'; p.write_bytes(b'bad')
            with self.assertRaises(ValueError):
                t.trial('adb', 'fastboot', p, {}, 30)
            devices.assert_not_called()

    def test_preflight_failure_never_reboots(self):
        bad = baseline(); bad['properties']['ro.build.fingerprint'] = 'wrong'
        with patch.object(t, 'verify_image'), patch.object(t, 'one_device', return_value='S'), \
             patch.object(t.capture, 'capture', return_value=bad), patch.object(t, 'call') as call:
            with self.assertRaises(ValueError):
                t.trial('adb', 'fastboot', Path('image'), {}, 30)
            call.assert_not_called()

    def test_temporary_boot_failure_never_falls_back_to_flash(self):
        calls = []
        def invoke(tool, args, serial=None, timeout=15):
            calls.append((tool, args))
            return {'returncode': 1 if args[0] == 'boot' else 0, 'output': 'not supported'}
        with patch.object(t, 'verify_image'), patch.object(t, 'one_device', return_value='S'), \
             patch.object(t.capture, 'capture', return_value=baseline()), \
             patch.object(t, 'bootloader', return_value=bootloader()), \
             patch.object(t, 'call', side_effect=invoke), patch.object(t, 'observe') as observe:
            report = {}
            with self.assertRaises(ValueError):
                t.trial('adb', 'fastboot', Path('image'), report, 30)
            self.assertEqual(calls, [('adb', ['reboot', 'bootloader']), ('fastboot', ['boot', 'image'])])
            observe.assert_not_called()
            self.assertEqual(report['outcome'], 'temporary_boot_rejected_or_unknown')

    def test_bootloader_failure_never_sends_boot(self):
        with patch.object(t, 'verify_image'), patch.object(t, 'one_device', return_value='S'), \
             patch.object(t.capture, 'capture', return_value=baseline()), \
             patch.object(t, 'bootloader', side_effect=ValueError('slot differs')), \
             patch.object(t, 'call', return_value={'returncode': 0, 'output': ''}) as call:
            with self.assertRaises(ValueError):
                t.trial('adb', 'fastboot', Path('image'), {}, 30)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(call.call_args.args[1], ['reboot', 'bootloader'])

    def test_stock_fallback_is_not_success(self):
        for release, expected in ((t.STOCK_RELEASE, 'different_kernel_build_or_slot_observed'),
                                  (t.TEST_RELEASE, 'candidate_android_boot_observed')):
            after = baseline(); after['queries']['kernel_release']['stdout'] = release
            with patch.object(t, 'one_device', return_value='S'), \
                 patch.object(t, 'call', return_value={'returncode': 0, 'output': '1'}), \
                 patch.object(t.capture, 'capture', return_value=after):
                report = {'before': baseline()}
                t.observe('adb', 'S', report, 30)
                self.assertEqual(report['outcome'], expected)

    def test_return_stock_only_reboots_and_rejects_other_product(self):
        for product in ('annibale', 'myron'):
            def invoke(tool, args, serial=None):
                return {'returncode': 0, 'output': product if args[0] == 'shell' else ''}
            with patch.object(t, 'one_device', return_value='S'), \
                 patch.object(t, 'call', side_effect=invoke) as call:
                if product == 'annibale':
                    t.return_stock('adb', 'fastboot', {})
                    self.assertEqual(call.call_args.args[1], ['reboot'])
                else:
                    with self.assertRaises(ValueError):
                        t.return_stock('adb', 'fastboot', {})
                    self.assertEqual(call.call_count, 1)


if __name__ == '__main__':
    unittest.main()
