#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare an exact OS4.0.6 AuthSecret extraction-list patch, without copying blobs.

Only the file inventory changes. No interfaces, credentials, service lifecycle,
firmware or policy are modified. This does not qualify the HAL on a native ROM.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path

from annibale_ramdisk import require
from audit_annibale_vendor_blobs import parse_list

OLD_MANIFEST = 'odm/etc/vintf/manifest/vendor.xiaomi.hardware.authsecretd.xml'
NEW_MANIFEST = 'odm/etc/vintf/manifest/vendor.xiaomi.hardware.miauthsecretd.xml'
OLD_LIBRARY = 'odm/lib64/libmi_authsecretd.so'
NEW_LIBRARY = 'vendor/lib64/vendor.xiaomi.hardware.oldcredential-V1-ndk.so'
EXISTING_LIBRARY = 'odm/lib64/vendor.xiaomi.hardware.miauthsecretd-V1-ndk.so'


def convert(text):
    require(text.endswith('\n'), 'proprietary list must end with newline')
    entries = parse_list(text)
    sources = {e['source'] for e in entries}
    destinations = {e['destination'] for e in entries}
    require(NEW_MANIFEST not in sources | destinations and NEW_LIBRARY not in sources | destinations,
            'new OS4 owner already exists; review the list')
    for path in (OLD_MANIFEST, OLD_LIBRARY, EXISTING_LIBRARY):
        require(text.splitlines().count(path) == 1, 'unreviewed AuthSecret extraction entry: '+path)
    after = text.replace(OLD_MANIFEST+'\n', NEW_MANIFEST+'\n')
    after = after.replace(OLD_LIBRARY+'\n', '')
    after = after.replace(EXISTING_LIBRARY+'\n', EXISTING_LIBRARY+'\n'+NEW_LIBRARY+'\n')
    require(after != text, 'no extraction change')
    parse_list(after)
    return after


def verify_assets(root, manifest):
    require(manifest['firmware_label'] == 'OS4.0.6.0.XPKCNXM', 'wrong firmware asset profile')
    for part, relative in (('vendor', 'build.prop'), ('odm', 'etc/build.prop')):
        path = root/part/relative
        require(not path.is_symlink() and path.resolve().is_relative_to(root.resolve()), 'unsafe property path')
        text = path.read_text()
        expected = f'ro.{part}.build.version.incremental='+manifest['incremental']
        require(text.splitlines().count(expected) == 1, 'vendor/odm build mismatch')
    for name, expected in manifest['files'].items():
        path = root/name
        require(not path.is_symlink() and path.resolve().is_relative_to(root.resolve()), 'unsafe asset path')
        require(path.is_file() and path.stat().st_size == expected['size'], 'missing/wrong-sized asset: '+name)
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected['sha256'], 'asset hash mismatch: '+name)
    require(all(not (root/name).exists() and not (root/name).is_symlink()
                for name in (OLD_MANIFEST, OLD_LIBRARY)), 'old assets unexpectedly present')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dump', type=Path, required=True)
    ap.add_argument('--proprietary-files', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    profile = Path(__file__).resolve().parents[1]/'Documentation/xiaomi/annibale-os406-authsecret-assets.json'
    manifest = json.loads(profile.read_text())
    verify_assets(args.dump, manifest)
    before = args.proprietary_files.read_text()
    after = convert(before)
    output = args.output.resolve()
    require(not output.exists(), 'output already exists')
    require(args.dump.resolve() not in output.parents and args.proprietary_files.resolve() not in output.parents,
            'output overlaps input')
    patch = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                    fromfile='a/proprietary-files.txt', tofile='b/proprietary-files.txt'))
    output.mkdir(parents=True)
    (output/'annibale-os406-authsecret.patch').write_text(patch)
    (output/'proprietary-files.txt').write_text(after)
    report = {'status': 'exact_stock_assets_and_list_patch_prepared', 'firmware_label': manifest['firmware_label'],
              'before_sha256': hashlib.sha256(before.encode()).hexdigest(),
              'after_sha256': hashlib.sha256(after.encode()).hexdigest(), 'files_verified': manifest['files'],
              'hal_abi_verified': False, 'service_or_policy_changed': False, 'rom_built': False,
              'remaining': ['Other missing blob paths', 'Generated build owners and native linker namespaces',
                            'VINTF compatibility, enforcing SELinux and runtime credential behavior']}
    (output/'validation.json').write_text(json.dumps(report, indent=2)+'\n')
    print('PASS: OS4 AuthSecret manifest and oldcredential extraction inputs; runtime unverified')


if __name__ == '__main__':
    main()
