#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare an exact annibale OS4 display/video extraction-list migration.

Use the entire matching OS4 blob set. This is not a compatibility shim for OS3,
does not change a running system, and does not qualify display/video on hardware.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path

from annibale_ramdisk import require
from audit_annibale_vendor_blobs import parse_list, safe_path


def convert(text, profile):
    require(text.endswith('\n'), 'proprietary list must end with newline')
    entries = parse_list(text)
    owners = {p for e in entries for p in [e['source'], e['destination']] + e['symlinks']}
    for old, new in profile['relocations'].items():
        require(text.splitlines().count(old) == 1, 'unreviewed old media owner: '+old)
        require(new not in owners, 'new media owner already exists: '+new)
    for name in profile['absent_other_platform_firmware']:
        require(text.splitlines().count(name) == 1, 'unreviewed old video owner: '+name)
    after = ''.join(profile['relocations'].get(line, line)+'\n'
                    for line in text.splitlines()
                    if line not in profile['absent_other_platform_firmware'])
    for name in profile['retained_sun_firmware']:
        require(text.splitlines().count(name) == 1 and after.splitlines().count(name) == 1,
                'must retain selected sun firmware: '+name)
    parse_list(after)
    return after


def verify_assets(root, profile, repository):
    root = root.resolve()
    require(profile['firmware_label'] == 'OS4.0.6.0.XPKCNXM', 'wrong firmware profile')
    for part, relative in (('vendor','build.prop'), ('odm','etc/build.prop')):
        path = root/part/relative
        require(not path.is_symlink() and path.resolve().is_relative_to(root), 'unsafe build property path')
        text = path.read_text()
        expected = f'ro.{part}.build.version.incremental='+profile['incremental']
        require(text.splitlines().count(expected) == 1, 'vendor/odm build mismatch')
    for name, expected in profile['files'].items():
        path = root/safe_path(name)
        require(not path.is_symlink() and path.resolve().is_relative_to(root), 'unsafe media asset path')
        require(path.is_file() and path.stat().st_size == expected['size'], 'missing/wrong-sized media asset: '+name)
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected['sha256'], 'media asset hash mismatch: '+name)
    for name in list(profile['relocations']) + profile['absent_other_platform_firmware']:
        path = root/safe_path(name)
        require(not path.exists() and not path.is_symlink(), 'old media asset unexpectedly present: '+name)
    video = profile['video_source']
    path = repository/safe_path(video['path'])
    require(path.resolve().is_relative_to(repository.resolve()) and not path.is_symlink(), 'unsafe video source path')
    require(hashlib.sha256(path.read_bytes()).hexdigest() == video['sha256'], 'unreviewed video platform source')
    require('.fwname = "'+video['fwname']+'"' in path.read_text(), 'sun firmware selection changed')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dump', type=Path, required=True)
    ap.add_argument('--proprietary-files', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    repository = Path(__file__).resolve().parents[1]
    profile = json.loads((repository/'Documentation/xiaomi/annibale-os406-media-assets.json').read_text())
    verify_assets(args.dump, profile, repository)
    before = args.proprietary_files.read_text()
    after = convert(before, profile)
    output = args.output.resolve()
    require(not output.exists() and args.dump.resolve() not in output.parents, 'output exists/overlaps dump')
    patch = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                    fromfile='a/proprietary-files.txt', tofile='b/proprietary-files.txt'))
    output.mkdir(parents=True)
    (output/'annibale-os406-media.patch').write_text(patch)
    (output/'proprietary-files.txt').write_text(after)
    report = {'status':'exact_stock_media_inputs_prepared', 'firmware_label':profile['firmware_label'],
              'before_sha256':hashlib.sha256(before.encode()).hexdigest(),
              'after_sha256':hashlib.sha256(after.encode()).hexdigest(),
              'relocations':profile['relocations'], 'removed_absent_other_platform_firmware':profile['absent_other_platform_firmware'],
              'retained_sun_firmware':profile['retained_sun_firmware'], 'verified_files':profile['files'],
              'rom_built':False, 'display_video_runtime_verified':False,
              'unverified':['Complete matching blob set, generated owners and linker/policy checks',
                            'Display SR behavior and video codec/protected playback on hardware']}
    (output/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: ten display models moved to ODM and sun video firmware retained; runtime unverified')


if __name__ == '__main__':
    main()
