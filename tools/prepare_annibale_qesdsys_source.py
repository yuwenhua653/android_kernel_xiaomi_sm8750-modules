#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Supply the pinned QESD system APK and correct its native-ROM privilege path.

Requires androguard==4.1.3. Platform re-signing happens in the Android build;
this tool neither signs nor installs an APK, and does not qualify QESD runtime.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from annibale_ramdisk import require
from audit_annibale_vendor_blobs import parse_list, safe_path
from prepare_annibale_os4_telephony import verify_edges

ANDROID = '{http://schemas.android.com/apk/res/android}'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pinned(root, entries):
    root = root.resolve()
    result = {}
    for name, expected in entries.items():
        p = root / safe_path(name)
        require(p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root), 'missing/unsafe input: ' + name)
        data = p.read_bytes()
        require(sha(data) == expected, 'unreviewed input: ' + name)
        result[name] = data
    return result


def convert(text, profile):
    require(sha(text.encode()) == profile['input_sha256']['proprietary-files.txt'], 'extraction list drift')
    entries = parse_list(text)
    require(text.splitlines().count(profile['old_entry']) == 1, 'missing/changed QESD APK owner')
    old = next(e for e in entries if e['source'] == profile['apk_source'])
    require(old['flags'] == [] and old['destination'] == profile['apk_source'], 'unexpected APK signing/destination')
    destination = safe_path(profile['apk_destination'])
    require(destination.startswith('system_ext/priv-app/'), 'QESD service must be privileged system_ext')
    new = profile['apk_source'] + ':' + destination + '|' + profile['apk_sha1']
    anchor = '# QESD\n' + profile['old_entry'] + '\n'
    require(text.count(anchor) == 1, 'QESD section anchor changed')
    # Keep the one supplemental APK separately selectable: extracting the whole
    # QESD section from this source would also request unavailable managers/libs.
    after = text.replace(anchor, '# QESD system service\n' + new + '\n\n# QESD\n')
    parse_list(after)
    return after


def check_policy(seapp, contexts, te, profile):
    selectors = []
    for line in seapp.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        values = dict(token.split('=', 1) for token in line.split() if '=' in token)
        if values.get('name') == profile['package']:
            selectors.append(values)
    expected = dict(user='system', seinfo='platform', name=profile['package'], isPrivApp='true',
                    domain='vendor_qesdk_app', type='system_app_data_file')
    require(selectors == [expected], 'QESD app domain selector drift')
    mappings = [line.split() for line in contexts.splitlines() if line.split() and line.split()[0] == profile['binder_instance']]
    require(mappings == [[profile['binder_instance'], 'u:object_r:vendor_qesdk_service:s0']], 'QESD binder context drift')
    if te is not None:
        require('add_service(vendor_qesdk_app, vendor_qesdk_service);' in te.splitlines(), 'missing QESD service registration rule')
    return expected


def verify_apk(path, profile):
    require(path.is_file() and not path.is_symlink(), 'APK must be a regular file')
    data = path.read_bytes()
    require(sha(data) == profile['apk_sha256'] and hashlib.sha1(data).hexdigest() == profile['apk_sha1'], 'unreviewed APK')
    from loguru import logger
    logger.disable('androguard')
    from androguard.core.apk import APK
    from androguard.core.dex import DEX
    apk = APK(str(path))
    root = apk.get_android_manifest_xml()
    require(apk.get_package() == profile['package'] and root.get(ANDROID + 'sharedUserId') == 'android.uid.system', 'APK identity/UID drift')
    require(apk.get_min_sdk_version() == '31' and apk.get_target_sdk_version() == '36', 'APK SDK drift')
    require(apk.get_services() == [profile['service']] and profile['receiver'] in apk.get_receivers(), 'service/receiver drift')
    app = root.find('application')
    require(app.get(ANDROID + 'directBootAware') == 'true' and app.get(ANDROID + 'defaultToDeviceProtectedStorage') == 'true', 'early boot storage contract drift')
    actions = {a.get(ANDROID + 'name') for a in app.findall('receiver/intent-filter/action')}
    require({'android.intent.action.BOOT_COMPLETED', 'android.intent.action.LOCKED_BOOT_COMPLETED'} <= actions, 'boot receiver actions missing')
    require(not apk.get_libraries() and not any(n.startswith('lib/') for n in apk.get_files()), 'unreviewed native/shared library dependency')
    methods = {}
    for dex in apk.get_all_dex():
        for cls in DEX(dex).get_classes():
            for method in cls.get_methods():
                require(not method.get_access_flags() & 0x100, 'unreviewed JNI method')
                key = cls.get_name() + '->' + method.get_name() + method.get_descriptor()
                if key in profile['return_methods'] or any(key.startswith(p) for p in profile['required_call_edges']):
                    require(key not in methods, 'duplicate method')
                    methods[key] = [i.get_name() + ' ' + i.get_output() for i in method.get_instructions()]
    for name, expected in profile['return_methods'].items():
        require(methods.get(name) == expected, 'Binder version/hash implementation drift')
    edges = verify_edges(methods, profile['required_call_edges'])
    service_code = methods['Lvendor/qti/frameworks/utils/QesdkSysService;->onCreate()V']
    require(any(i.startswith('const-string ') and '"' + profile['binder_instance'] + '"' in i for i in service_code), 'wrong registered Binder name')
    return data, {'call_edges': edges, 'interface_hash': profile['interface_hash'], 'interface_version': profile['interface_version'], 'no_jni_methods': True}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('apk', 'stock', 'qcom-system-policy', 'device-tree', 'output'):
        ap.add_argument('--' + name, type=Path, required=True)
    args = ap.parse_args()
    repo = Path(__file__).resolve().parents[1]
    profile = json.loads((repo / 'Documentation/xiaomi/annibale-qesdsys-source.json').read_text())
    out = args.output.resolve()
    require(not out.exists() and not any(out.is_relative_to(p.resolve()) for p in (args.stock, args.device_tree, args.qcom_system_policy))
            and not args.apk.resolve().is_relative_to(out), 'output exists/overlaps inputs')
    before = pinned(args.device_tree, profile['input_sha256'])
    stock = pinned(args.stock, profile['stock_sha256'])
    policy = pinned(args.qcom_system_policy, profile['policy_sha256'])
    after = convert(before['proprietary-files.txt'].decode(), profile)
    data, evidence = verify_apk(args.apk, profile)
    require(profile['interface_hash'].encode() + b'\0' in stock[profile['api_provider']], 'stock AIDL V4 hash missing')
    manifest = ET.fromstring(stock['system_ext/etc/vintf/manifest/vendor.qti.qesdsys.service.xml'])
    require(manifest.get('type') == 'framework' and len([h for h in manifest.findall('hal') if h.get('format') == 'aidl'
            and h.findtext('name') == 'vendor.qti.qesdsys' and h.findtext('fqname') == 'IQesdSys/default']) == 1, 'stock framework instance missing')
    check_policy(stock['system_ext/etc/selinux/system_ext_seapp_contexts'].decode(),
                 stock['system_ext/etc/selinux/system_ext_service_contexts'].decode(), None, profile)
    evidence['policy_selector'] = check_policy(policy['generic/private/seapp_contexts'].decode(),
        policy['generic/private/service_contexts'].decode(), policy['generic/private/qesdkSystem.te'].decode(), profile)
    patch = ''.join(difflib.unified_diff(before['proprietary-files.txt'].decode().splitlines(True), after.splitlines(True),
                    fromfile='a/proprietary-files.txt', tofile='b/proprietary-files.txt'))
    out.mkdir(parents=True)
    target = out / 'source' / safe_path(profile['apk_source'])
    target.parent.mkdir(parents=True)
    target.write_bytes(data)
    (out / 'proprietary-files.txt').write_text(after)
    (out / 'annibale-qesdsys-source.patch').write_text(patch)
    report = {'round': 'R39', 'profile': profile, 'evidence': evidence, 'output_list_sha256': sha(after.encode()),
              'supplemental_apk_inputs': 1, 'requires_platform_resigning': True, 'manager_binaries_integrated': False,
              'rom_built': False, 'policy_compiled': False, 'runtime_verified': False, 'flashable': False}
    (out / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: QESD system APK source and privileged install mapping prepared; runtime unverified')


if __name__ == '__main__':
    main()
