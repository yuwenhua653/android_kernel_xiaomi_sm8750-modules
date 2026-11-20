#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only, non-root ADB capture for annibale boot qualification (Python 3.8+)."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

PROPERTIES = (
    'ro.product.device', 'ro.product.vendor.device', 'ro.product.odm.device',
    'ro.build.fingerprint', 'ro.vendor.build.fingerprint', 'ro.build.version.incremental',
    'ro.build.version.release', 'ro.build.version.sdk', 'ro.build.version.security_patch',
    'ro.boot.slot_suffix', 'ro.boot.verifiedbootstate', 'ro.boot.flash.locked',
    'ro.boot.vbmeta.device_state', 'ro.boot.avb_version', 'ro.boot.hardware',
    'ro.boot.boot_devices', 'ro.boot.dynamic_partitions', 'ro.boot.force_normal_boot',
    'ro.boot.load_modules_parallel', 'sys.boot_completed', 'vendor.all.modules.ready',
)
MOUNTS = {'/', '/data', '/metadata', '/vendor', '/vendor_dlkm', '/system_dlkm', '/odm'}


def execute(argv, timeout=12):
    try:
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout, check=False)
        return {'status': 'ok' if result.returncode == 0 else 'error',
                'returncode': result.returncode,
                'stdout': result.stdout.decode('utf-8', errors='replace').strip(),
                'stderr': result.stderr.decode('utf-8', errors='replace').strip()}
    except subprocess.TimeoutExpired:
        return {'status': 'timeout', 'stdout': '', 'stderr': 'command timed out'}
    except OSError as error:
        return {'status': 'error', 'stdout': '', 'stderr': type(error).__name__}


def choose_device(output):
    rows = [line.split() for line in output.splitlines()[1:] if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != 'device':
        raise ValueError('Connect exactly one authorized ADB device; unlock the screen and accept USB debugging.')
    return rows[0][0]


def filtered_mounts(raw):
    result = []
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[1] in MOUNTS:
            result.append({'mountpoint': fields[1], 'filesystem': fields[2],
                           'read_only': 'ro' in fields[3].split(',')})
    return result


def module_names(raw):
    return sorted({line.split()[0] for line in raw.splitlines()
                   if line.split() and re.fullmatch(r'[A-Za-z0-9_]+', line.split()[0])})


def assess(properties, mounts):
    data = {m['filesystem'] for m in mounts if m['mountpoint'] == '/data'}
    return {'device_matches': 'annibale' in {properties.get('ro.product.device'),
                                           properties.get('ro.product.vendor.device')},
            'userdata_filesystems': sorted(data),
            'userdata_check': 'blocked_mifs_not_in_candidate' if 'mifs' in data else
            'f2fs_observed' if data == {'f2fs'} else 'needs_review',
            'firmware_matches_baseline': properties.get('ro.build.version.incremental') == 'OS4.0.6.0.XPKCNXM',
            'flash_ready': False,
            'note': 'Read-only evidence; unlocked properties do not prove a safe installation or restore method.'}


def capture(adb, serial):
    def shell(*args):
        item = execute([adb, '-s', serial, 'shell', *args])
        # Never save transport identifiers even if an ADB error contains one.
        for key in ('stdout', 'stderr'):
            item[key] = item[key].replace(serial, '[device]')
        return item

    report = {'schema_version': 1, 'capture_utc': datetime.now(timezone.utc).isoformat(),
              'mode': 'read_only_no_root', 'queries': {}, 'properties': {}}
    for index, name in enumerate(PROPERTIES):
        if index % 6 == 0:
            print('Reading boot properties %d/%d...' % (index + 1, len(PROPERTIES)), flush=True)
        item = shell('getprop', name)
        report['queries'][name] = item
        report['properties'][name] = item['stdout'] if item['status'] == 'ok' else None
    if 'annibale' not in {report['properties'].get('ro.product.device'),
                          report['properties'].get('ro.product.vendor.device')}:
        report['assessment'] = {'flash_ready': False, 'device_matches': False,
                                'note': 'Device identity is not annibale; hardware collection stopped.'}
        return report
    print('Reading kernel, mount and module evidence...', flush=True)
    for name, command in (
        ('kernel_release', ('uname', '-r')),
        ('selinux', ('getenforce',)),
        ('kernel_tainted', ('cat', '/proc/sys/kernel/tainted')),
        ('module_signature_enforced', ('cat', '/sys/module/module/parameters/sig_enforce')),
        ('device_tree_model', ('cat', '/sys/firmware/devicetree/base/model')),
        ('device_tree_compatible', ('cat', '/sys/firmware/devicetree/base/compatible')),
        ('panel_name', ('cat', '/sys/class/drm/card0-DSI-1/panel_name')),
        ('panel_id', ('cat', '/sys/class/drm/card0-DSI-1/panel_id')),
    ):
        report['queries'][name] = shell(*command)
    # The disk hashes identify the staged network modules; presence and hashes
    # alone do not prove successful probe or packet processing.
    for module in ('rmnet_offload', 'rmnet_core', 'rmnet_shs'):
        report['queries'][module + '_file_sha256'] = shell(
            'sha256sum', '/vendor/lib/modules/' + module + '.ko')
    mounts = shell('cat', '/proc/mounts')
    report['mounts'] = filtered_mounts(mounts.pop('stdout'))
    report['queries']['mounts'] = mounts
    modules = shell('cat', '/proc/modules')
    report['loaded_module_names'] = module_names(modules.pop('stdout'))
    report['queries']['modules'] = modules
    inputs = shell('cat', '/sys/class/input/input*/name')
    # Input names may contain personal Bluetooth names: retain only known touch vendors.
    report['touch_input_names'] = [line for line in inputs.pop('stdout').splitlines()
                                   if re.fullmatch(r'(goodix|fts|focaltech)[A-Za-z0-9_ .-]*', line, re.I)]
    report['queries']['touch_inputs'] = inputs
    report['assessment'] = assess(report['properties'], report['mounts'])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default='adb', help='Uses PATH by default; may supply an adb executable path')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent / 'results')
    args = parser.parse_args()
    adb = shutil.which(args.adb)
    if not adb:
        parser.exit(1, 'ADB was not found. Install platform-tools and add adb to PATH.\n')
    devices = execute([adb, 'devices'])
    if devices['status'] != 'ok':
        parser.exit(1, 'ADB device discovery failed. Check the cable and platform-tools.\n')
    try:
        serial = choose_device(devices['stdout'])
    except ValueError as error:
        parser.exit(1, str(error) + '\n')
    print('Collecting read-only boot evidence; no root, reboot, flashing or phone writes.')
    report = capture(adb, serial)
    args.output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = args.output / ('annibale-boot-readiness-' + stamp + '.zip')
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('readiness.json', json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('SEND THIS ZIP: ' + str(target.resolve()))
    print(json.dumps(report['assessment'], ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
