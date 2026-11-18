#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify OS4 integrated RIL audio, retire its old APK and enforce the APK SDK floor.

Install androguard==4.1.3 in an isolated Python environment for APK/DEX checks.
No APK patching, minimum-SDK lowering, stock modification or hardware test.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from annibale_ramdisk import require
from audit_annibale_vendor_blobs import audit, parse_list, safe_path, SUPPORTED_PARTITIONS


def sha(data):
    return hashlib.sha256(data).hexdigest()


def convert(before, profile, guard):
    for name, expected in profile['inputs'].items():
        require(sha(before[name].encode()) == expected, 'unreviewed input: ' + name)
    require(sha(guard.encode()) == profile['guard_sha256'], 'SDK guard template changed')
    lines = before['proprietary-files.txt'].splitlines()
    parse_list(before['proprietary-files.txt'])
    for line in [profile['retired_entry']] + profile['retained_entries']:
        require(lines.count(line) == 1, 'changed telephony entry: ' + line)
    require(profile['retired_entry'] not in profile['retained_entries'], 'active provider retired')
    after = dict(before)
    after['proprietary-files.txt'] = '\n'.join(l for l in lines if l != profile['retired_entry']) + '\n'
    parse_list(after['proprietary-files.txt'])
    anchor = '# Generic ramdisk allow list\n'
    require(before['device.mk'].count(anchor) == 1, 'device product anchor changed')
    require('OS4.0.6 APKs require' not in before['device.mk'], 'SDK guard already installed')
    after['device.mk'] = before['device.mk'].replace(anchor, guard + '\n' + anchor)
    return after


def verify_edges(methods, requirements):
    edges = {}
    for prefix, required in requirements.items():
        matches = [v for k, v in methods.items() if k.startswith(prefix)]
        require(len(matches) == 1, 'missing/ambiguous audio method: ' + prefix)
        calls = [s for s in matches[0] if s.startswith('invoke-')]
        for target in required:
            require(any(target in s for s in calls), 'missing audio call edge: ' + target)
        edges[prefix] = required
    return edges


def verify_stock(root, text, profile):
    # Import only here so pure conversion tests do not require APK tooling.
    from loguru import logger
    logger.disable('androguard')
    from androguard.core.apk import APK
    from androguard.core.dex import DEX

    require(profile['firmware'] == 'OS4.0.6.0.XPKCNXM', 'wrong profile')
    for name, expected in profile['assets'].items():
        path = root / safe_path(name)
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root), 'unsafe asset: ' + name)
        require(sha(path.read_bytes()) == expected, 'stock asset changed: ' + name)
    require('ro.vendor.build.version.incremental=OS4.0.6.0.XPKCN' in (root / 'vendor/build.prop').read_text().splitlines(), 'wrong stock version')
    old = root / safe_path(profile['retired_entry'])
    require(not old.exists() and not old.is_symlink(), 'legacy APK now present')
    selected = {e['source'] for e in parse_list(text) if e['source'].endswith(('.apk', '.jar')) and e['source'] != profile['retired_entry']}
    # Euicc remains absent and unresolved. Every present selected archive must be pinned.
    present = {n for n in selected if (root / n).exists()}
    require(present == {a['source'] for a in profile['archives']}, 'selected archive set drift')
    archive_report = []
    phone = None
    for item in profile['archives']:
        name = safe_path(item['source'])
        path = root / name
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root), 'unsafe archive: ' + name)
        require(sha(path.read_bytes()) == item['sha256'], 'archive changed: ' + name)
        with ZipFile(path) as archive:
            for entry in archive.namelist():
                if entry.endswith('.dex') or entry == 'AndroidManifest.xml':
                    data = archive.read(entry)
                    for token in profile['legacy_archive_tokens']:
                        require(token.encode() not in data and token.encode('utf-16le') not in data, 'legacy service consumer: ' + name)
        if name.endswith('.apk'):
            apk = APK(str(path))
            require(apk.get_package() == item['package'] and apk.get_min_sdk_version() == item['min_sdk'], 'APK manifest drift: ' + name)
            archive_report.append({'source': name, 'package': apk.get_package(), 'min_sdk': apk.get_min_sdk_version()})
            if apk.get_package() == 'com.qti.phone':
                require(phone is None, 'duplicate QtiTelephony provider')
                phone = apk
    require(phone is not None, 'missing integrated provider')
    floor = max(int(a['min_sdk'] or '1') for a in archive_report)
    require(floor == profile['minimum_platform_sdk'], 'APK SDK floor changed')
    permissions = {'android.permission.RECEIVE_BOOT_COMPLETED', 'android.permission.MODIFY_AUDIO_ROUTING', 'android.permission.MODIFY_AUDIO_SETTINGS'}
    require(permissions <= set(phone.get_permissions()), 'integrated audio permissions missing')
    require('com.qti.phone.ExtTelephonyService' in phone.get_services() and 'com.qti.phone.QtiTelephonyBootReceiver' in phone.get_receivers(), 'integrated service/receiver missing')
    methods = {}
    for raw in phone.get_all_dex():
        for cls in DEX(raw).get_classes():
            for method in cls.get_methods():
                key = cls.get_name() + '->' + method.get_name() + method.get_descriptor()
                if any(key.startswith(p) for p in profile['required_call_edges']):
                    require(key not in methods, 'duplicate audio method')
                    methods[key] = [i.get_name() + ' ' + i.get_output() for i in method.get_instructions()]
    return {'selected_archives_scanned': len(profile['archives']), 'legacy_archive_reference_hits': [], 'minimum_platform_sdk': floor, 'apps_requiring_sdk_37': [a for a in archive_report if int(a['min_sdk'] or '1') == 37], 'audio_call_edges': verify_edges(methods, profile['required_call_edges']), 'audio_permissions_declared': sorted(permissions), 'permissions_granted_on_device': False}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dump', type=Path, required=True)
    ap.add_argument('--device-tree', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    root, out = args.dump.resolve(), args.output.resolve()
    require(not out.exists() and not out.is_relative_to(root) and not out.is_relative_to(args.device_tree.resolve()), 'output exists/overlaps inputs')
    repo = Path(__file__).resolve().parents[1]
    profile = json.loads((repo / 'Documentation/xiaomi/annibale-os406-telephony-assets.json').read_text())
    guard = (repo / 'tools/templates/os406-telephony/sdk-check.mk').read_text()
    before = {n: (args.device_tree / safe_path(n)).read_text() for n in profile['inputs']}
    after = convert(before, profile, guard)
    evidence = verify_stock(root, before['proprietary-files.txt'], profile)
    result = audit(root, after['proprietary-files.txt'], SUPPORTED_PARTITIONS)
    patch = ''.join(''.join(difflib.unified_diff(before[n].splitlines(True), after[n].splitlines(True), fromfile='a/' + n, tofile='b/' + n)) for n in after)
    out.mkdir(parents=True)
    for name, data in after.items():
        (out / name).write_text(data)
    (out / 'annibale-os406-telephony.patch').write_text(patch)
    (out / 'all-partitions-audit.json').write_text(json.dumps(result, indent=2) + '\n')
    report = {'round': 'R37', 'resolution': 'retain integrated QtiTelephony audio provider, retire legacy APK and require platform API >= 37', 'input_sha256': profile['inputs'], 'output_sha256': {n: sha(t.encode()) for n, t in after.items()}, 'after_counts': result['counts'], 'evidence': evidence, 'remaining': [{'source': e['source'], 'section': e['section']} for e in result['entries'] if e['status'] != 'present'], 'runtime_verified': False, 'rom_built': False, 'policy_compiled': False, 'flashable': False}
    (out / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: integrated telephony migration and SDK guard prepared; ' + json.dumps(result['counts']) + '; runtime unverified')


if __name__ == '__main__':
    main()
