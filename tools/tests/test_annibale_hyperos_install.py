# SPDX-License-Identifier: GPL-2.0-only
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install_annibale_hyperos as i


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = {'serial': 'TESTSERIAL', 'slot': 'b', 'payload_sha256': i.PAYLOAD_SHA}
        self.session = i.Session(self.root, 'adb', 'fastboot', self.state)
        self.mode = False; self.calls = []; self.overrides = {}; self.fail_flash = None
        self.addCleanup(patch.stopall)
        patch.object(i, 'verify_payload', return_value={}).start()
        patch.object(i.time, 'sleep').start()
        patch.object(i.trial, 'one_device', return_value='TESTSERIAL').start()
        patch.object(i.trial, 'call', side_effect=self.call).start()

    def call(self, executable, args, serial, timeout=120):
        self.assertEqual(serial, 'TESTSERIAL'); self.calls.append(args)
        if args[0] == 'getvar':
            values = {'product': 'annibale', 'current-slot': 'b', 'unlocked': 'yes',
                      'is-userspace': 'yes' if self.mode else 'no',
                      'partition-size:boot_b': '0x6000000', 'partition-size:vbmeta_b': '0x10000',
                      'partition-size:vendor_dlkm_b': hex(55910400),
                      'snapshot-update-status': 'none', 'is-logical:vendor_dlkm_b': 'yes'}
            values.update(self.overrides)
            return {'returncode': 0, 'output': args[1] + ': ' + values[args[1]]}
        if args[:2] == ['reboot', 'fastboot']: self.mode = True
        if args[:2] == ['reboot', 'bootloader']: self.mode = False
        if args[0] == 'flash' and args[1] == self.fail_flash:
            return {'returncode': None, 'output': 'timeout'}
        return {'returncode': 0, 'output': 'OKAY'}

    def writes(self):
        return [x for x in self.calls if x[0] == 'flash']

    def test_only_current_slot_three_images(self):
        self.session.write_set('candidate')
        self.assertEqual([x[1] for x in self.writes()], ['vendor_dlkm_b', 'boot_b', 'vbmeta_b'])
        self.assertTrue(all('/candidate/' in x[2] for x in self.writes()))
        self.assertEqual(self.calls[-1], ['reboot'])
        self.assertEqual(self.state['status'], 'candidate_written_unverified')
        self.assertFalse(any(x[0] in ('erase', 'set_active', 'flashing', 'resize-logical-partition') for x in self.calls))

    def test_restore_from_fastbootd_uses_stock_only(self):
        self.mode = True
        self.session.write_set('stock-rollback')
        self.assertTrue(all('/stock-rollback/' in x[2] for x in self.writes()))
        self.assertEqual(self.state['status'], 'stock_images_restored_unverified')

    def test_device_slot_lock_snapshot_and_size_guards(self):
        for key, value in [('product', 'myron'), ('current-slot', 'a'), ('unlocked', 'no'),
                           ('snapshot-update-status', 'merging'), ('snapshot-update-status', 'unknown'),
                           ('is-logical:vendor_dlkm_b', 'no'), ('partition-size:vendor_dlkm_b', '0x10'),
                           ('partition-size:boot_b', '0x10'), ('partition-size:vbmeta_b', '0x10')]:
            with self.subTest(key=key, value=value):
                self.calls=[]; self.mode=False; self.overrides={key:value}
                with self.assertRaises(ValueError): self.session.write_set('candidate')
                self.assertEqual(self.writes(), [])

    def test_failure_after_each_write_never_continues_or_reboots(self):
        for p in ['vendor_dlkm_b', 'boot_b', 'vbmeta_b']:
            with self.subTest(partition=p):
                self.calls=[]; self.mode=False; self.fail_flash=p
                with self.assertRaises(ValueError): self.session.write_set('candidate')
                self.assertEqual(self.calls[-1][0:2], ['flash',p])
                state=json.loads((self.root/'state-r49.json').read_text())
                self.assertEqual(state['pending_partition'],p[:-2])

    def test_changed_serial_never_writes(self):
        with patch.object(i.trial, 'one_device', return_value='OTHER'):
            with self.assertRaises(ValueError): self.session.write_set('candidate')
        self.assertFalse(self.calls)

    def test_invalid_state_never_guesses_slot(self):
        for changes in [{'slot':'c'}, {'serial':''}, {'payload_sha256':'old'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                i.check_state(dict(self.state, **changes))


class PayloadTests(unittest.TestCase):
    def test_modified_payload_image_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); inv={}
            for group in ('candidate','stock-rollback'):
                (root/group).mkdir()
                for part in i.PARTITIONS:
                    p=root/group/(part+'.img');p.write_bytes(b'test')
                    inv[p.relative_to(root).as_posix()]={'size':4,'sha256':hashlib.sha256(b'test').hexdigest()}
            raw=json.dumps(inv).encode();(root/'payload.json').write_bytes(raw)
            with patch.object(i,'PAYLOAD_SHA',hashlib.sha256(raw).hexdigest()):
                i.verify_payload(root)
                (root/'candidate/boot.img').write_bytes(b'evil')
                with self.assertRaises(ValueError):i.verify_payload(root)
            with self.assertRaises(ValueError):i.verify_payload(root)


if __name__ == '__main__':unittest.main()
