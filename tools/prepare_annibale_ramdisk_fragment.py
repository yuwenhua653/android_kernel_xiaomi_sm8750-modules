#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Pack a verified native normal-boot module fragment, never a flashable image.

Keep platform fstab, init_boot, recovery and DLKM filesystem ownership separate.
The original vendor_boot is read only for layout/bootconfig comparison; none of
its modules or fstab are copied into the native fragment.
"""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import subprocess

from annibale_ramdisk import read_newc, require, serial_bootconfig, vendor_v4

STOCK_VENDOR_BOOT_SHA = '38d4b91165578133a2c1626f343599356959d771e2ae061c47627dcdbafd962a'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('stage', 'policy', 'stock-vendor-boot', 'mkbootfs', 'lz4', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    stage = args.stage.resolve()
    validation = json.loads((stage / 'validation.json').read_text())
    manifest = json.loads((stage / 'manifest.json').read_text())
    policy_bytes = args.policy.read_bytes()
    policy = json.loads(policy_bytes)
    require(validation['status'] == 'android_stage_passed' and validation['complete_device'] is False and
            validation['policy_sha256'] == sha(policy_bytes), 'stale/unqualified native stage')
    require(policy['profile'] == 'native-source-qualification' and policy['boot_mode'] == 'normal' and
            policy['wireless_profile'] == 'annibale-kiwi' and
            policy['audio_variant'] == validation['audio_variant'], 'wrong native policy')
    # Bind the recorded result as well as all installed early files.
    require(sha((stage / 'validation.json').read_bytes()) == manifest['validation.json']['sha256'],
            'stage validation changed')
    ramdisk = stage / 'vendor_boot'
    files = {}
    for path in ramdisk.rglob('*'):
        require(not path.is_symlink(), 'symlink in staged ramdisk')
        if path.is_dir():
            continue
        relative = str(path.relative_to(stage))
        require(path.is_file() and relative in manifest, 'unrecorded ramdisk file')
        data = path.read_bytes()
        require(sha(data) == manifest[relative]['sha256'] and len(data) == manifest[relative]['size'],
                'staged ramdisk file changed')
        files[str(path.relative_to(ramdisk))] = data
    expected = {name.removeprefix('vendor_boot/') for name in manifest if name.startswith('vendor_boot/')}
    require(files.keys() == expected, 'staged ramdisk file missing')
    index_names = {'modules.dep', 'modules.alias', 'modules.softdep', 'modules.load'}
    require(all(name.startswith('lib/modules/') and
                (Path(name).suffix == '.ko' or Path(name).name in index_names) for name in files),
            'unexpected ramdisk owner (platform/recovery/stock contents are not accepted)')
    listed = files['lib/modules/modules.load'].decode().splitlines()
    early = {item['destination'].removeprefix('vendor_boot/'): item
             for item in validation['modules'] if item['destination'].startswith('vendor_boot/')}
    require(len(listed) == len(set(listed)) == len(early) and
            {'lib/modules/' + name for name in listed} == early.keys(), 'early module list mismatch')
    for name, item in early.items():
        require(sha(files[name]) == item['installed_sha256'], 'module differs from strip/ELF validation')
    stock = args.stock_vendor_boot.read_bytes()
    require(sha(stock) == STOCK_VENDOR_BOOT_SHA, 'wrong original vendor_boot baseline')
    sections, layout = vendor_v4(stock)
    require(len(layout['entries']) == 1 and layout['entries'][0]['type'] == 1,
            'original platform ramdisk selection changed')
    native_config = serial_bootconfig(sections['bootconfig'], layout['cmdline'])
    out = args.output.resolve()
    require(not out.exists(), 'output must not exist')
    require(stage not in out.parents and out not in stage.parents, 'output overlaps the verified stage')
    out.mkdir(parents=True)
    cpio = subprocess.check_output([str(args.mkbootfs), str(ramdisk)])
    parsed = read_newc(cpio)
    regular = {n: entry for n, entry in parsed.items() if stat.S_ISREG(entry['mode'])}
    require(regular.keys() == files.keys(), 'packed ramdisk member set changed')
    for name, data in files.items():
        item = regular[name]
        require(item['data'] == data and item['uid'] == item['gid'] == 0 and
                stat.S_IMODE(item['mode']) == 0o644, 'packed bytes/ownership/mode changed: ' + name)
    require({n for n in parsed if n not in regular} == {'lib', 'lib/modules'}, 'unexpected directory layout')
    for name in ('lib', 'lib/modules'):
        entry = parsed[name]
        require(entry['uid'] == entry['gid'] == 0 and stat.S_IMODE(entry['mode']) == 0o755,
                'wrong packed directory ownership/mode')
    raw = out / 'vendor_dlkm_fragment.cpio'
    raw.write_bytes(cpio)
    packed = out / 'vendor_dlkm_fragment.lz4'
    with packed.open('wb') as stream:
        subprocess.run([str(args.lz4), '-l', '-12', '-c', str(raw)], stdout=stream, stderr=subprocess.PIPE, check=True)
    require(packed.read_bytes()[:4] == bytes.fromhex('02214c18'), 'wrong legacy LZ4 format')
    roundtrip = subprocess.check_output([str(args.lz4), '-d', '-c', str(packed)])
    require(roundtrip == cpio, 'compressed fragment roundtrip mismatch')
    (out / 'bootconfig-native-candidate.txt').write_bytes(native_config)
    stock_cpio = subprocess.check_output([str(args.lz4), '-d', '-c'], input=sections['ramdisk'])
    stock_entries = read_newc(stock_cpio)
    stock_load = stock_entries['lib/modules/modules.load']['data'].decode().splitlines()
    fstab = stock_entries['first_stage_ramdisk/fstab.qcom']['data']
    report = {'schema_version': 1, 'status': 'fragment_passed', 'flashable': False, 'complete_device': False,
              'boot_verified': False, 'family': policy['audio_variant'], 'release': validation['release'],
              'policy_sha256': sha(policy_bytes), 'stage_validation_sha256': sha((stage / 'validation.json').read_bytes()),
              'early_modules': len(early), 'archive_members': len(parsed), 'required_vendor_ramdisk_type': 3,
              'cpio_sha256': sha(cpio), 'lz4_sha256': sha(packed.read_bytes()),
              'bootconfig_sha256': sha(native_config), 'bootconfig_change': 'androidboot.load_modules_parallel=false',
              'source_stock_vendor_boot_sha256': sha(stock), 'stock_layout': layout,
              'stock_ramdisk': {'members': len(stock_entries), 'modules': sum(n.endswith('.ko') for n in stock_entries),
                                'normal_load_roots': len(stock_load), 'fstab_sha256': sha(fstab)},
              'tools_sha256': {n: sha(getattr(args, n).read_bytes()) for n in ('mkbootfs', 'lz4')},
              'unverified': ['Complete native platform ramdisk/fstab and init_boot integration',
                             'Final vendor_boot table/fragments, DTBO choice, AVB and recovery',
                             'Actual init first-stage insertion/probe and SELinux',
                             'Complete native module plan, DLKM filesystem images, firmware and HALs']}
    (out / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'README.txt').write_text('PARTIAL NORMAL-BOOT NATIVE MODULE FRAGMENT; NOT FLASHABLE.\n'
                                  'Contains /lib/modules only, no fstab/init or stock/recovery modules.\n'
                                  'Integrate as a DLKM (type 3) vendor ramdisk fragment with the selected native platform ramdisk.\n'
                                  'Replace conflicting parallel bootconfig owners; do not append false after true.\n'
                                  'The generated bootconfig is an offline baseline-derived candidate, not a live HyperOS change.\n')
    print(f'PASS: {len(early)} early modules packed and roundtrip-checked; NOT a vendor_boot image')


if __name__ == '__main__':
    main()
