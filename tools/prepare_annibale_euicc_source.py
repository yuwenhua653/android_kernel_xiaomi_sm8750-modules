#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare a pinned, separately sourced EuiccGoogle input for the R37 ROM tree.

Requires androguard==4.1.3 and Android apksigner. Does not edit the stock dump,
enable hardware, install an APK on a phone or qualify a complete native ROM.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

from annibale_ramdisk import require
from audit_annibale_vendor_blobs import parse_list, safe_path

ANDROID = '{http://schemas.android.com/apk/res/android}'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def convert(before, profile):
    for name, expected in profile['input_sha256'].items():
        require(digest(before[name].encode()) == expected, 'unreviewed input: ' + name)
    text = before['proprietary-files.txt']
    entries = parse_list(text)
    old = profile['old_entry']
    require(text.splitlines().count(old) == 1, 'eSIM input changed/already migrated')
    selected = [e for e in entries if e['section'] == 'Euicc']
    require(len(selected) == 1 and selected[0]['flags'] == ['PRESIGNED'], 'ambiguous eSIM provider')
    source = safe_path(profile['new_source'])
    require(selected[0]['destination'] == source, 'eSIM destination changed')
    new = source + ';PRESIGNED|' + profile['sha1']
    result = '\n'.join(new if line == old else line for line in text.splitlines()) + '\n'
    parse_list(result)
    return result


def verify_manifest(root, allowlist, profile):
    require(root.get('package') == profile['package'], 'wrong APK package')
    require(root.get(ANDROID + 'versionCode') == profile['version_code'], 'APK version drift')
    require(root.get(ANDROID + 'sharedUserId') is None, 'unexpected shared UID')
    sdk = root.find('uses-sdk')
    require(sdk is not None and sdk.get(ANDROID + 'minSdkVersion') == profile['min_sdk']
            and sdk.get(ANDROID + 'targetSdkVersion') == profile['target_sdk'], 'APK SDK drift')
    app = root.find('application')
    require(app is not None, 'missing application')
    services = [s for s in app.findall('service') if s.get(ANDROID + 'name') == profile['euicc_service']]
    require(len(services) == 1, 'missing/duplicate LPA service')
    service = services[0]
    require(service.get(ANDROID + 'permission') == 'android.permission.BIND_EUICC_SERVICE'
            and service.get(ANDROID + 'exported') == 'true', 'unprotected/unavailable LPA service')
    filters = [f for f in service.findall('intent-filter') if any(
        a.get(ANDROID + 'name') == 'android.service.euicc.EuiccService' for a in f.findall('action'))]
    require(len(filters) == 1 and int(filters[0].get(ANDROID + 'priority', '0')) > 0,
            'LPA service cannot be selected')
    libraries = app.findall('uses-library')
    require(sorted(l.get(ANDROID + 'name') for l in libraries) == sorted(profile['optional_libraries'])
            and all(l.get(ANDROID + 'required') == 'false' for l in libraries), 'library dependency drift')
    packages = [p for p in ET.fromstring(allowlist).findall('privapp-permissions')
                if p.get('package') == profile['package']]
    require(len(packages) == 1, 'missing/duplicate product privilege allowlist')
    allowed = {p.get('name') for p in packages[0].findall('permission')}
    require(set(profile['privileged_permissions']) <= allowed, 'missing LPA privileged permission')
    return {'lpa_service': profile['euicc_service'], 'binding_permission_checked': True,
            'optional_libraries': profile['optional_libraries'], 'privilege_allowlist_checked': True}


def verify_apk(path, profile, signer, allowlist):
    require(path.is_file() and not path.is_symlink(), 'APK must be a regular file')
    data = path.read_bytes()
    require(len(data) == profile['size'] and digest(data) == profile['sha256']
            and hashlib.sha1(data).hexdigest() == profile['sha1'], 'unreviewed/corrupted APK')
    command = (['java', '-jar', signer] if signer.endswith('.jar') else [signer])
    result = subprocess.run(command + ['verify', '--verbose', '--print-certs', str(path)],
                            capture_output=True, text=True, check=True)
    certs = re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([0-9a-f]+)$', result.stdout, re.M)
    require(certs == [profile['certificate_sha256']], 'unexpected APK signer')
    from loguru import logger
    logger.disable('androguard')
    from androguard.core.apk import APK
    apk = APK(str(path))
    evidence = verify_manifest(apk.get_android_manifest_xml(), allowlist, profile)
    evidence.update(signature_verified=True, certificate_sha256=certs[0],
                    sha256=digest(data), byte_modifications=False)
    return data, evidence, result.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apk', type=Path, required=True)
    ap.add_argument('--device-tree', type=Path, required=True)
    ap.add_argument('--apksigner', default='apksigner', help='executable or apksigner.jar')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    repo = Path(__file__).resolve().parents[1]
    profile = json.loads((repo / 'Documentation/xiaomi/annibale-euicc-source.json').read_text())
    tree, out = args.device_tree.resolve(), args.output.resolve()
    require(not out.exists() and not out.is_relative_to(tree)
            and not args.apk.resolve().is_relative_to(out), 'output exists/overlaps inputs')
    before = {n: (tree / safe_path(n)).read_text() for n in profile['input_sha256']}
    after = convert(before, profile)
    data, evidence, signature_log = verify_apk(args.apk, profile, args.apksigner,
        before['configs/permissions/privapp-permissions-com.google.android.euicc.xml'])
    name = 'proprietary-files.txt'
    patch = ''.join(difflib.unified_diff(before[name].splitlines(True), after.splitlines(True),
                    fromfile='a/' + name, tofile='b/' + name))
    out.mkdir(parents=True)
    target = out / 'source' / safe_path(profile['new_source'])
    target.parent.mkdir(parents=True)
    target.write_bytes(data)
    (out / name).write_text(after)
    (out / 'annibale-euicc-source.patch').write_text(patch)
    (out / 'apksigner.txt').write_text(signature_log)
    report = {'round': 'R38', 'provenance': profile, 'evidence': evidence,
              'output_list_sha256': digest(after.encode()), 'source_files_supplied': 1,
              'stock_dump_modified': False, 'is_stock_os406_file': False,
              'qesd_inputs_supplied': 0, 'rom_built': False, 'runtime_verified': False}
    (out / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: separately sourced, signed eSIM input prepared; native ROM and hardware unverified')


if __name__ == '__main__':
    main()
