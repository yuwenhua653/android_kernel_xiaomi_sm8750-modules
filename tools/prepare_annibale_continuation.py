#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Recreate the R40 conversion, R42 init/fstab and R43 factory Wi-Fi adaptation.

No proprietary data is fetched, no vendor tree is generated, and no ROM is
built. Outputs must be new and separate from the clean pinned reference.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from annibale_ramdisk import require
from prepare_annibale_rom_handoff import convert as handoff
from prepare_annibale_os4_authsecret import convert as authsecret
from prepare_annibale_os4_media import convert as media
from prepare_annibale_os4_userspace import convert as userspace

REFERENCE = '1ed1eccfa3f68e1ec440b7f5e87ac97dc89475fe'
PATCHES = ('annibale-os406-services.patch', 'annibale-os406-camera-qape.patch',
           'annibale-os406-telephony.patch', 'annibale-euicc-source.patch',
           'annibale-qesdsys-source.patch', 'annibale-qesd-managers.patch',
           'annibale-native-init-owners.patch')


def prepare(reference, output):
    reference, output = reference.resolve(), output.resolve()
    repo = Path(__file__).resolve().parents[1]
    docs = repo/'Documentation/xiaomi'
    require(not output.exists(), 'output already exists')
    require(not output.is_relative_to(reference) and not reference.is_relative_to(output), 'overlapping paths')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(reference), *args], text=True).strip()
    require(git('rev-parse', 'HEAD') == REFERENCE, 'reference commit differs')
    require(not git('status', '--porcelain'), 'reference is dirty')
    shutil.copytree(reference, output, ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
    names = ('BoardConfig.mk', 'device.mk', 'proprietary-files.txt', 'rootdir/Android.bp')
    files, _ = handoff({name: (output/name).read_text() for name in names})
    for name, text in files.items():
        (output/name).write_text(text)
    # convert() rewrites existing owners only; the CLI patch also adds this file.
    # A continuation calling convert() directly must recreate that addition.
    shutil.copyfile(repo/'configs/annibale/native/fstab.qcom', output/'rootdir/etc/fstab.annibale-oss')
    listing = output/'proprietary-files.txt'
    listing.write_text(media(authsecret(listing.read_text()),
                             json.loads((docs/'annibale-os406-media-assets.json').read_text())))
    files = userspace({name: (output/name).read_text() for name in ('proprietary-files.txt', 'extract-files.py')},
                      json.loads((docs/'annibale-os406-userspace-assets.json').read_text()))
    for name, text in files.items():
        (output/name).write_text(text)
    for patch in PATCHES:
        subprocess.run(['git', '-C', str(output), 'apply', str(docs/'patches'/patch)], check=True)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    expected = json.loads((docs/'annibale-r40-validation.json').read_text())['prepared_list_sha256']
    require(digest(listing) == expected, 'final R40 extraction list differs')
    owner_profile = json.loads((docs/'annibale-native-init-owners.json').read_text())
    require(digest(output/'rootdir/etc/init.qcom.rc') == owner_profile['output_sha256'], 'init-owner correction differs')
    wifi_profile = json.loads((docs/'annibale-native-wifi-factory.json').read_text())
    for name, hashes in wifi_profile['files'].items():
        require(digest(output/name) == hashes['input_sha256'], 'factory Wi-Fi input changed: '+name)
    subprocess.run(['git', '-C', str(output), 'apply',
                    str(docs/'patches/annibale-native-wifi-factory.patch')], check=True)
    for name, hashes in wifi_profile['files'].items():
        require(digest(output/name) == hashes['output_sha256'], 'factory Wi-Fi output differs: '+name)
    require((output/'rootdir/etc/fstab.qcom').read_bytes() == (reference/'rootdir/etc/fstab.qcom').read_bytes(),
            'recovery fstab changed')
    report = {'status': 'device_source_restored', 'reference_commit': REFERENCE,
              'files_sha256': {str(p.relative_to(output)): digest(p) for p in sorted(output.rglob('*')) if p.is_file()},
              'new_fstab_included': True, 'recovery_fstab_unchanged': True,
              'proprietary_inputs_verified': False, 'vendor_generated': False, 'rom_built': False,
              'instructions': 'Install one R41 handoff separately; regenerate vendor with stock and R38-R40 supplements.'}
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--reference', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    args = ap.parse_args()
    report = prepare(args.reference, args.output)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: restored complete converted source tree including native fstab; ROM unbuilt')


if __name__ == '__main__':
    main()
