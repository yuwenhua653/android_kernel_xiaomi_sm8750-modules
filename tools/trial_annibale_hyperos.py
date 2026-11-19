#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""One-shot OS4.0.6 temporary boot test. Never flash, erase or switch slots."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
import zipfile

import capture_annibale_boot_readiness as capture

STOCK_RELEASE = '6.6.118-android15-8-g0908354dac1b-ab16143355-4k'
TEST_RELEASE = '6.6.144-4k-ge7af0d4f1111'
IMAGE_SHA = '7734eb703e5fb608a45cfc07afd5cf1b5189e903cb9981bce9daa44485475680'
IMAGE_BYTES = 36876288
PARTITION_BYTES = 100663296
SYSTEM_FP = 'Redmi/annibale/annibale:17/CP2A.260605.016/OS4.0.6.0.XPKCNXM:user/release-keys'
VENDOR_FP = 'Redmi/annibale/annibale:15/AQ3A.250226.002/OS4.0.6.0.XPKCN:user/release-keys'


def preflight(report):
    p = report.get('properties', {})
    expected = {'ro.product.device': 'annibale', 'ro.build.fingerprint': SYSTEM_FP,
                'ro.vendor.build.fingerprint': VENDOR_FP,
                'ro.build.version.incremental': 'OS4.0.6.0.XPKCNXM',
                'ro.boot.flash.locked': '0', 'ro.boot.verifiedbootstate': 'orange',
                'sys.boot_completed': '1'}
    bad = [name for name, value in expected.items() if p.get(name) != value]
    if p.get('ro.boot.slot_suffix') not in ('_a', '_b'):
        bad.append('slot')
    if report.get('queries', {}).get('kernel_release', {}).get('stdout') != STOCK_RELEASE:
        bad.append('stock kernel release')
    if report.get('queries', {}).get('selinux', {}).get('stdout') != 'Enforcing':
        bad.append('SELinux baseline')
    if {r['filesystem'] for r in report.get('mounts', []) if r['mountpoint'] == '/data'} != {'f2fs'}:
        bad.append('F2FS userdata baseline')
    if bad:
        raise ValueError('Baseline differs; test stopped: ' + ', '.join(bad))
    return p['ro.boot.slot_suffix'][1:]


def parse_devices(text, mode):
    if mode == 'adb':
        return capture.choose_device(text)
    rows = [line.split() for line in text.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != 'fastboot':
        raise ValueError('Connect exactly one bootloader fastboot device (not fastbootd).')
    return rows[0][0]


def parse_var(output, name):
    values = []
    for line in output.splitlines():
        line = re.sub(r'^\(bootloader\)\s*', '', line.strip())
        if line.startswith(name + ':'):
            values.append(line[len(name) + 1:].strip())
    if len(values) != 1:
        raise ValueError('Missing or ambiguous fastboot variable: ' + name)
    return values[0]


def check_bootloader(values, slot=None):
    if values.get('product') != 'annibale' or values.get('is-userspace') != 'no':
        raise ValueError('Requires annibale bootloader fastboot, not fastbootd.')
    if values.get('unlocked') != 'yes':
        raise ValueError('Bootloader did not confirm unlocked=yes; no unlock is attempted.')
    actual = values.get('current-slot')
    if actual not in ('a', 'b') or (slot is not None and actual != slot):
        raise ValueError('Bootloader slot differs; do not switch slots to bypass this check.')
    for name, required, exact in (('partition-size:boot_' + actual, PARTITION_BYTES, True),
                                  ('max-download-size', IMAGE_BYTES, False)):
        try:
            text = values[name]
            size = int(text, 16 if text.startswith('0x') or re.search('[a-fA-F]', text) else 10)
        except (KeyError, ValueError):
            raise ValueError('Invalid fastboot size: ' + name)
        if (exact and size != required) or (not exact and size < required):
            raise ValueError('Unexpected or insufficient fastboot size: ' + name)
    return actual


def verify_image(path):
    if not path.is_file() or path.stat().st_size != IMAGE_BYTES:
        raise ValueError('Missing or incorrect test image size.')
    if hashlib.sha256(path.read_bytes()).hexdigest() != IMAGE_SHA:
        raise ValueError('Test image SHA256 mismatch.')


def call(tool, args, serial=None, timeout=15):
    command = [tool] + (['-s', serial] if serial else []) + args
    try:
        proc = subprocess.run(command, capture_output=True, timeout=timeout)
        text = (proc.stdout + proc.stderr).decode('utf-8', errors='replace').strip()
        if serial:
            text = text.replace(serial, '[device]')
        return {'returncode': proc.returncode, 'output': text}
    except subprocess.TimeoutExpired:
        return {'returncode': None, 'output': 'command timed out; outcome unknown'}


def require(result):
    if result['returncode'] != 0:
        raise ValueError(result['output'])
    return result['output']


def one_device(tool, mode):
    return parse_devices(require(call(tool, ['devices'])), mode)


def get_var(fastboot, serial, name):
    return parse_var(require(call(fastboot, ['getvar', name], serial)), name)


def bootloader(fastboot, serial, slot=None):
    values = {name: get_var(fastboot, serial, name)
              for name in ('product', 'is-userspace', 'unlocked', 'current-slot')}
    actual = values['current-slot']
    if actual not in ('a', 'b'):
        raise ValueError('Invalid current-slot; stopped before querying partition.')
    for name in ('partition-size:boot_' + actual, 'max-download-size'):
        values[name] = get_var(fastboot, serial, name)
    check_bootloader(values, slot)
    return values


def save(report, output):
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = output / ('annibale-r45-trial-' + stamp + '.zip')
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('trial.json', json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('SEND THIS ZIP: ' + str(target.resolve()), flush=True)


def observe(adb, serial, report, seconds):
    print('Waiting up to %d seconds for ADB. Ctrl+C preserves the partial report.' % seconds, flush=True)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            current = one_device(adb, 'adb')
        except ValueError:
            time.sleep(2)
            continue
        if current != serial:
            raise ValueError('ADB device changed; collection stopped.')
        completed = call(adb, ['shell', 'getprop', 'sys.boot_completed'], serial)
        if completed['returncode'] == 0 and completed['output'] == '1':
            break
        time.sleep(2)
    else:
        report['outcome'] = 'no_completed_boot_observed'
        print('No completed ADB boot observed. If stuck, hold Power to restart the original system.', flush=True)
        return
    report['after'] = capture.capture(adb, serial)
    release = report['after']['queries']['kernel_release']['stdout']
    p = report['after'].get('properties', {})
    slot_ok = not report.get('before') or p.get('ro.boot.slot_suffix') == report['before']['properties']['ro.boot.slot_suffix']
    report['outcome'] = ('candidate_android_boot_observed' if release == TEST_RELEASE and
                         p.get('ro.build.fingerprint') == SYSTEM_FP and slot_ok else
                         'different_kernel_build_or_slot_observed')
    if report.get('before'):
        before = set(report['before'].get('loaded_module_names', []))
        after = set(report['after'].get('loaded_module_names', []))
        report['module_names_missing_after'] = sorted(before - after)
        report['module_names_added_after'] = sorted(after - before)
    report['hardware_functional_tests'] = 'User observation required; module presence is not functional proof.'
    print(report['outcome'], flush=True)


def trial(adb, fastboot, image, report, seconds):
    verify_image(image)
    serial = one_device(adb, 'adb')
    report['before'] = capture.capture(adb, serial)
    slot = preflight(report['before'])
    report['baseline_passed'] = True
    report['image_sha256'] = IMAGE_SHA
    print('Baseline matched. Rebooting to bootloader for ONE temporary boot; no partition writes.', flush=True)
    require(call(adb, ['reboot', 'bootloader'], serial))
    deadline = time.monotonic() + 60
    while True:
        try:
            fb_serial = one_device(fastboot, 'fastboot')
            break
        except ValueError:
            if time.monotonic() > deadline:
                raise ValueError('Fastboot not detected; check the Windows bootloader driver. No boot command sent.')
            time.sleep(2)
    if fb_serial != serial:
        raise ValueError('ADB/fastboot serial differs; stopped with original partitions intact.')
    report['bootloader'] = bootloader(fastboot, serial, slot)
    # Validate again immediately before use, never substitute a different image.
    verify_image(image)
    report['temporary_boot'] = call(fastboot, ['boot', str(image)], serial, timeout=120)
    if report['temporary_boot']['returncode'] != 0:
        report['outcome'] = 'temporary_boot_rejected_or_unknown'
        raise ValueError('Temporary boot failed or timed out. Do not flash as a fallback. Use return-stock or hold Power.')
    observe(adb, serial, report, seconds)


def return_stock(adb, fastboot, report):
    # Temporary boot changes no boot image. A normal reboot selects the existing stock image.
    try:
        serial = one_device(adb, 'adb')
    except ValueError:
        serial = one_device(fastboot, 'fastboot')
        if get_var(fastboot, serial, 'product') != 'annibale':
            raise ValueError('Not annibale; reboot stopped.')
        if get_var(fastboot, serial, 'is-userspace') != 'no':
            raise ValueError('Exit fastbootd manually to bootloader first.')
        require(call(fastboot, ['reboot'], serial))
    else:
        product = require(call(adb, ['shell', 'getprop', 'ro.product.device'], serial))
        if product != 'annibale':
            raise ValueError('Not annibale; reboot stopped.')
        require(call(adb, ['reboot'], serial))
    report['outcome'] = 'normal_reboot_requested_not_yet_verified'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('trial', 'collect', 'return-stock'))
    p.add_argument('--seconds', type=int, default=180, choices=range(30, 601))
    a = p.parse_args()
    root = Path(__file__).resolve().parent
    adb, fastboot = shutil.which('adb'), shutil.which('fastboot')
    if not adb or not fastboot:
        p.exit(1, 'Install Python 3.8+ and Android platform-tools; adb and fastboot must be on PATH.\n')
    report = {'schema_version': 1, 'action': a.action, 'flash_ready': False,
              'partition_flash_commands': False, 'outcome': 'not_started',
              'time_utc': datetime.now(timezone.utc).isoformat()}
    result = 0
    try:
        if a.action == 'trial':
            trial(adb, fastboot, root / 'boot-UNQUALIFIED.img', report, a.seconds)
        elif a.action == 'collect':
            serial = one_device(adb, 'adb')
            observe(adb, serial, report, a.seconds)
        else:
            return_stock(adb, fastboot, report)
    except (ValueError, OSError, KeyError) as error:
        report['error'] = str(error)
        print('STOP: ' + str(error), flush=True)
        result = 1
    except KeyboardInterrupt:
        report['interrupted'] = True
        print('\nStopped. If the candidate is stuck, hold Power to restart the original system.', flush=True)
        result = 130
    finally:
        save(report, root / 'results')
    return result


if __name__ == '__main__':
    raise SystemExit(main())
