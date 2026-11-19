#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare all seven pinned QESD manager inputs after R39.

Writes an isolated source directory and extraction-list patch; never edits the
dump/device tree. This native-ROM supplement is not a stock-HyperOS installer.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from annibale_ramdisk import require
from audit_annibale_vendor_blobs import parse_list
from prepare_annibale_qesdsys_source import pinned, sha


def repair_policy(data, additions):
    text = data.decode()
    rules = {}
    for line in text.splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        require(':' in line, 'unexpected seccomp directive')
        name, expression = (s.strip() for s in line.split(':', 1))
        require(name not in rules, 'duplicate syscall rule')
        rules[name] = expression
    require(rules.get('socket') == 'arg0 == AF_UNIX', 'socket restriction drift')
    for name in ('mmap', 'mprotect'):
        require(rules.get(name) == 'arg2 in ~PROT_EXEC || arg2 in ~PROT_WRITE', 'W^X restriction drift')
    require(not set(additions) & rules.keys() and len(set(additions)) == len(additions), 'syscall already present/duplicated')
    return (text + '\n# Required by QESD socket replies and the Bionic/library lifecycle.\n' +
            ''.join(name + ': 1\n' for name in additions)).encode()


def convert(text, files, profile):
    require(sha(text.encode()) == profile['input_sha256']['proprietary-files.txt'], 'extraction list drift')
    entries = parse_list(text)
    for name in files:
        owners = [e for e in entries if e['source'] == name or e['destination'] == name]
        require(len(owners) == 1 and owners[0]['source'] == name and owners[0]['destination'] == name
                and not owners[0]['flags'] and owners[0]['section'] == 'QESD', 'unexpected/duplicate owner: ' + name)
        require(text.splitlines().count(name) == 1, 'unreviewed pin: ' + name)
    require(text.splitlines().count('# QESD') == 1, 'QESD section drift')
    retained = '\n'.join(line for line in text.splitlines() if line not in files) + '\n'
    block = '# QESD manager supplement\n' + ''.join(name + '|' + hashlib.sha1(data).hexdigest() + '\n'
                                                       for name, data in files.items())
    after = retained.replace('# QESD\n', block + '\n# QESD\n')
    parsed = parse_list(after)
    require({e['source'] for e in parsed if e['section'] == 'QESD manager supplement'} == set(files), 'section ownership error')
    return after


def contracts(files, policy, board):
    for name, service, socket in [('qesdk-manager', 'vendor.qesdk-mgr', 'qesd'),
                                  ('qesdk-secmanager', 'vendor.qesdk-securitymgr', 'qesdsec')]:
        lines = [line.strip() for line in files['vendor/etc/init/' + name + '.rc'].decode().splitlines()
                 if line.strip() and not line.lstrip().startswith('#')]
        require(lines.count('service ' + service + ' /vendor/bin/' + name) == 1, 'init binary/service mismatch')
        require(all(x in lines for x in ('class hal', 'user system', 'group system',
                                        'socket ' + socket + ' seqpacket 666 root system')), 'init identity/socket drift')
        require(not any(x.startswith(('seclabel ', 'disabled', 'oneshot')) for x in lines), 'unexpected init override')
    require('mkdir /data/vendor/qesdk 0777 root system' in files['vendor/etc/init/qesdk-manager.rc'].decode(), 'database directory missing')
    root = ET.fromstring(files['vendor/etc/vintf/manifest/qesdk-manager.xml'])
    hals = root.findall('hal')
    require(root.get('type') == 'device' and len(hals) == 1 and hals[0].get('format') == 'aidl'
            and hals[0].findtext('name') == 'vendor.qti.qesdhalaidl' and hals[0].findtext('version') == '2'
            and hals[0].findtext('fqname') == 'IQesdhal/default', 'manager VINTF mismatch')
    require('include device/qcom/sepolicy_vndr/sm8750/SEPolicy.mk' in board.splitlines(), 'Qualcomm policy not included')
    contexts = policy['qva/vendor/common/file_contexts'].decode()
    expected = {'/vendor/bin/qesdk-manager': 'vendor_hal_qesdhal_default_exec',
                '/vendor/bin/qesdk-secmanager': 'vendor_qesdsect_exec',
                '/dev/socket/qesd': 'vendor_qesd_socket', '/dev/socket/qesdsec': 'vendor_qesdsec_socket',
                '/data/vendor/qesdk(/.*)?': 'vendor_qesdk_data_file'}
    for path, label in expected.items():
        require(re.search(r'^' + re.escape(path) + r'\s+u:object_r:' + label + ':s0$', contexts, re.M), 'missing context: ' + path)
    for path, rules in {
        'qva/vendor/common/qesdhal.te': ['init_daemon_domain(vendor_hal_qesdhal_default)',
            'hal_attribute_service(vendor_hal_qesdhal, vendor_hal_qesdhalaidl_service)',
            'unix_socket_connect(vendor_hal_qesdhal_default, vendor_qesdsec, vendor_qesdsect)'],
        'qva/vendor/common/qesdsecurity.te': ['init_daemon_domain(vendor_qesdsect)',
            'unix_socket_connect(vendor_qesdsect, vendor_ssgtzd, vendor_ssgtzd)']}.items():
        text = policy[path].decode()
        require(all(rule in text for rule in rules), 'missing policy contract: ' + path)
        require(not re.search(r'^\s*permissive\s', text, re.M), 'unexpected permissive domain')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('donor', 'stock', 'qcom-policy', 'device-tree', 'output'):
        ap.add_argument('--' + name, type=Path, required=True)
    args = ap.parse_args()
    repo = Path(__file__).resolve().parents[1]
    profile = json.loads((repo / 'Documentation/xiaomi/annibale-qesd-managers.json').read_text())
    out = args.output.resolve()
    require(not out.exists() and not any(out.is_relative_to(p.resolve()) or p.resolve().is_relative_to(out)
            for p in (args.donor, args.stock, args.qcom_policy, args.device_tree)), 'output exists/overlaps inputs')
    before = pinned(args.device_tree, profile['input_sha256'])
    files = pinned(args.donor, profile['donor_sha256'])
    stock = pinned(args.stock, profile['stock_contract_sha256'])
    policy = pinned(args.qcom_policy, profile['policy_sha256'])
    contracts(files, policy, before['BoardConfig.mk'].decode())
    require(not any(h.findtext('name') == 'vendor.qti.qesdhalaidl'
                    for h in ET.fromstring(before['vintf/manifest.xml']).findall('hal')), 'duplicate device QESD instance')
    for name in ('vendor/bin/ssgtzd', 'vendor/etc/init/ssgtzd.rc'):
        require(before['proprietary-files.txt'].decode().splitlines().count(name) == 1, 'missing secure-service owner: ' + name)
    ssgtzd = stock['vendor/etc/init/ssgtzd.rc'].decode()
    require(all(x in ssgtzd for x in ('service vendor.ssgtzd /vendor/bin/ssgtzd',
        'start vendor.ssgtzd', 'socket ssgtzd stream 0660 system oem_2912')), 'secure-service startup/socket drift')
    for name, additions in profile['seccomp_additions'].items():
        files[name] = repair_policy(files[name], additions)
    require({n: sha(d) for n, d in files.items()} == profile['output_sha256'], 'prepared content drift')
    after = convert(before['proprietary-files.txt'].decode(), files, profile)
    patch = ''.join(difflib.unified_diff(before['proprietary-files.txt'].decode().splitlines(True), after.splitlines(True),
                                       fromfile='a/proprietary-files.txt', tofile='b/proprietary-files.txt'))
    out.mkdir(parents=True)
    for name, data in files.items():
        target = out / 'source' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if name.startswith('vendor/bin/'):
            target.chmod(0o755)
    (out / 'proprietary-files.txt').write_text(after)
    (out / 'annibale-qesd-managers.patch').write_text(patch)
    (out / 'validation.json').write_text(json.dumps({'round': 'R40', 'profile': profile,
        'supplemental_inputs': len(files), 'output_list_sha256': sha(after.encode()),
        'rom_built': False, 'policy_compiled': False, 'runtime_verified': False, 'flashable': False}, indent=2) + '\n')
    print('PASS: seven QESD inputs prepared together; runtime unverified')


if __name__ == '__main__':
    main()
