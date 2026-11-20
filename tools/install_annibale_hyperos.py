#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Explicit install/restore for an OS4.0.6 annibale offline candidate.

Does not unlock, relock, erase, resize, disable verification or change slots.
The distributor binds PAYLOAD_SHA to the verified image inventory when packing.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import time

import trial_annibale_hyperos as trial

PAYLOAD_SHA = '@PAYLOAD_SHA@'
PARTITIONS = ('boot', 'vendor_dlkm', 'vbmeta')


def verify_payload(root):
    raw = (root / 'payload.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != PAYLOAD_SHA:
        raise ValueError('Image inventory checksum differs.')
    inventory = json.loads(raw)
    expected = {group + '/' + name + '.img' for group in ('candidate', 'stock-rollback') for name in PARTITIONS}
    if set(inventory) != expected:
        raise ValueError('Unexpected image inventory.')
    for name, record in inventory.items():
        p = root / name
        if p.is_symlink() or not p.is_file() or p.stat().st_size != record['size']:
            raise ValueError('Image missing or wrong size: ' + name)
        if hashlib.sha256(p.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Image checksum differs: ' + name)
    return inventory


def check_state(state):
    if state.get('payload_sha256') != PAYLOAD_SHA or state.get('slot') not in ('a', 'b'):
        raise ValueError('State does not match this package/slot.')
    if not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', state.get('serial', '')):
        raise ValueError('Missing or invalid original device identity.')
    return state


class Session:
    def __init__(self, root, adb, fastboot, state):
        self.root, self.adb, self.fastboot, self.state = root, adb, fastboot, check_state(state)
        self.serial, self.slot = state['serial'], state['slot']

    def save(self):
        path = self.root / 'state-r49.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.state, indent=2) + '\n')
        temp.replace(path)

    def command(self, args, timeout=120):
        result = trial.call(self.fastboot, args, self.serial, timeout=timeout)
        self.state.setdefault('commands', []).append({'args': args, **result})
        self.save()
        if result['returncode'] != 0:
            raise ValueError('Command failed or outcome unknown; stopped without further writes/reboot. Use restore with this state. ' + ' '.join(args))
        return result['output']

    def var(self, name):
        return trial.parse_var(self.command(['getvar', name]), name)

    def wait(self):
        deadline = time.monotonic() + 60
        while True:
            try:
                serial = trial.one_device(self.fastboot, 'fastboot')
            except ValueError:
                if time.monotonic() > deadline:
                    raise ValueError('Fastboot not found; check USB driver. Preserve state-r49.json.')
                time.sleep(1)
                continue
            if serial != self.serial:
                raise ValueError('Device identity changed; stopped.')
            return

    def check(self, userspace):
        self.wait()
        if self.var('product') != 'annibale' or self.var('current-slot') != self.slot:
            raise ValueError('Product or current slot differs; no slot switch is attempted.')
        if self.var('is-userspace') != ('yes' if userspace else 'no'):
            raise ValueError('Wrong fastboot mode.')
        if not userspace and self.var('unlocked') != 'yes':
            raise ValueError('Requires unlocked=yes; no unlock is attempted.')

    def size(self, partition, minimum, maximum):
        value = self.var('partition-size:' + partition + '_' + self.slot)
        if not re.fullmatch(r'(?:0x)?[0-9a-fA-F]+', value):
            raise ValueError('Invalid partition size.')
        size = int(value, 16 if value.startswith('0x') or re.search('[a-fA-F]', value) else 10)
        if not minimum <= size <= maximum:
            raise ValueError('Unexpected partition size; no resize is attempted: ' + partition)

    def to_bootloader(self):
        self.wait()
        if self.var('product') != 'annibale' or self.var('current-slot') != self.slot:
            raise ValueError('Device/slot differs.')
        mode = self.var('is-userspace')
        if mode == 'yes':
            self.command(['reboot', 'bootloader']); time.sleep(2)
        elif mode != 'no':
            raise ValueError('Unknown fastboot mode.')
        self.check(False)

    def flash(self, partition, group):
        # Recheck all six payload images before every partition write.
        verify_payload(self.root)
        self.check(partition == 'vendor_dlkm')
        self.state['pending_partition'] = partition
        self.save()
        self.command(['flash', partition + '_' + self.slot,
                      str(self.root / group / (partition + '.img'))], timeout=180)
        self.state['pending_partition'] = None
        self.state.setdefault('written', []).append({'group': group, 'partition': partition})
        self.save()

    def write_set(self, group):
        if group not in ('candidate', 'stock-rollback'):
            raise ValueError('Unknown image group.')
        verify_payload(self.root)
        self.to_bootloader()
        self.size('boot', 100663296, 100663296)
        # Stock vbmeta image is 12 KiB; its physical partition may be larger.
        self.size('vbmeta', 12288, 1048576)
        self.command(['reboot', 'fastboot']); time.sleep(2)
        self.check(True)
        if self.var('snapshot-update-status') != 'none':
            raise ValueError('OTA snapshot state is active or unknown; no changes made. Do not cancel or merge it with this script.')
        if self.var('is-logical:vendor_dlkm_' + self.slot) != 'yes':
            raise ValueError('vendor_dlkm is not the expected logical partition.')
        self.size('vendor_dlkm', 55910400, 55910400)
        self.flash('vendor_dlkm', group)
        self.command(['reboot', 'bootloader']); time.sleep(2)
        self.check(False)
        self.flash('boot', group)
        self.flash('vbmeta', group)
        self.state['status'] = 'candidate_written_unverified' if group == 'candidate' else 'stock_images_restored_unverified'
        self.save()
        self.command(['reboot'])
        print(self.state['status'] + '. Device boot/hardware behavior must still be checked.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('verify', 'install', 'restore'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    try:
        verify_payload(root)
        if args.action == 'verify':
            print('PASS: all six candidate/rollback image checksums and sizes. No device accessed.')
            return 0
        adb, fastboot = shutil.which('adb'), shutil.which('fastboot')
        if not adb or not fastboot:
            raise ValueError('Python 3 and Android platform-tools adb/fastboot must be on PATH.')
        state_path = root / 'state-r49.json'
        if args.action == 'install':
            if state_path.exists():
                raise ValueError('Existing installation state: use restore, do not overwrite it or repeat install.')
            serial = trial.one_device(adb, 'adb')
            before = trial.capture.capture(adb, serial)
            slot = trial.preflight(before)
            state = {'serial': serial, 'slot': slot, 'payload_sha256': PAYLOAD_SHA,
                     'status': 'prepared_no_writes', 'commands': [], 'written': []}
            session = Session(root, adb, fastboot, state)
            session.save()
            # Save local evidence only. It is never uploaded automatically.
            (root / 'baseline-r49.json').write_text(json.dumps(before, indent=2) + '\n')
            trial.require(trial.call(adb, ['reboot', 'bootloader'], serial))
            session.write_set('candidate')
        else:
            if not state_path.is_file():
                raise ValueError('Original installation state missing. No slot or device identity will be guessed.')
            session = Session(root, adb, fastboot, json.loads(state_path.read_text()))
            session.write_set('stock-rollback')
        return 0
    except (ValueError, OSError, KeyError) as error:
        print('STOP: ' + str(error))
        print('Keep state-r49.json. If writes began, enter bootloader and use restore; a normal reboot alone does not restore flashed images.')
        return 1
    except KeyboardInterrupt:
        print('Interrupted. Preserve state-r49.json; any started write may have completed. Use restore.')
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
