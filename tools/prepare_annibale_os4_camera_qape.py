#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Retire pinned OS4 legacy camera/QAPE inputs, preserving current providers.

This is a version-specific extraction-list migration, not a hardware fix or an
equivalence claim for the old camera models. Input stock and device tree are
read-only. Output includes a concrete patch and the complete partition audit.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from annibale_ramdisk import require
from audit_annibale_vendor_blobs import audit, parse_list, safe_path, SUPPORTED_PARTITIONS
from prepare_annibale_os4_userspace import elf_dynamic


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inventory_digest(items):
    return sha(json.dumps(items, sort_keys=True, separators=(',', ':')).encode())


def stream_matches(path, tokens):
    needles = {t: t.encode() for t in tokens}
    overlap = max(map(len, needles.values())) - 1
    tail, found = b'', set()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            data = tail + chunk
            found.update(t for t, n in needles.items() if n in data)
            tail = data[-overlap:] if overlap else b''
    return sorted(found)


def convert(text, profile):
    require(sha(text.encode()) == profile['input_sha256'], 'unreviewed extraction list')
    entries = parse_list(text)
    sources = {e['source'] for e in entries}
    lines = text.splitlines()
    retired = profile['retired_entries']
    require(len(set(retired)) == len(retired), 'duplicate retirement')
    require(set(profile['retained_sources']) <= sources, 'missing active provider input')
    require(not set(retired).intersection(profile['retained_sources']), 'active provider retired')
    for name in retired:
        require(lines.count(name) == 1, 'changed legacy entry: ' + name)
    result = '\n'.join(line for line in lines if line not in retired) + '\n'
    after = parse_list(result)
    require(len(entries) - len(after) == len(retired), 'unexpected extraction-list delta')
    return result


def verify_stock(root, text, profile):
    require(profile['firmware'] == 'OS4.0.6.0.XPKCNXM', 'wrong firmware profile')
    for part, rel in [('vendor', 'build.prop'), ('odm', 'etc/build.prop')]:
        path = root / part / rel
        require(path.is_file() and not path.is_symlink(), 'unsafe build properties')
        require(f'ro.{part}.build.version.incremental=OS4.0.6.0.XPKCN' in path.read_text().splitlines(), 'wrong stock version')
    for name, expected in profile['assets'].items():
        path = root / safe_path(name)
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root), 'missing/unsafe provider: ' + name)
        require(path.stat().st_size == expected['size'] and sha(path.read_bytes()) == expected['sha256'], 'changed provider: ' + name)
    for name in profile['retired_entries']:
        path = root / safe_path(name)
        require(not path.exists() and not path.is_symlink(), 'legacy input now present: ' + name)
    before = audit(root, text, SUPPORTED_PARTITIONS)
    camera = [{k: e[k] for k in ('source', 'resolved_source', 'size', 'sha256')}
              for e in before['entries'] if e['status'] == 'present' and e['section'].startswith('Camera')]
    require(len(camera) == profile['camera_inventory_count'] and inventory_digest(camera) == profile['camera_inventory_sha256'], 'camera inventory drift')
    for item in camera:
        hits = stream_matches(root / item['resolved_source'], profile['forbidden_camera_tokens'])
        require(not hits, 'legacy camera reference: ' + item['source'] + ': ' + ','.join(hits))
    perf_name = 'vendor/bin/hw/vendor.qti.hardware.perf2-hal-service'
    perf = (root / perf_name).read_bytes()
    for token in [b'BnQapeC2Ev', b'registerQape', b'Qape: Failed to register to Snapdragon Services', b'/vendor/lib64/libqape_oem_ext.so']:
        require(token in perf, 'missing integrated QAPE evidence')
    require(b'qsap_qapeservice.policy' not in perf, 'old QAPE sandbox still required')
    dynamic = elf_dynamic(root / perf_name)
    require({'vendor.qti.snapdragonServices-V1-ndk.so', 'vendor.qti.snapdragonServices.qape-V1-ndk.so'} <= set(dynamic['needed']), 'QAPE interface dependency drift')
    cil = (root / 'vendor/etc/selinux/vendor_sepolicy.cil').read_text()
    require('(typeattributeset vendor_hal_snapx_service_qti_client (vendor_hal_perf_default))' in cil, 'stock QAPE policy relation changed')
    for filename, name, fqname in [('vendor.qti.hardware.perf2.xml', 'vendor.qti.hardware.perf2', 'IPerf/default'), ('snapdragon_services.xml', 'vendor.qti.snapdragonServices', 'ISnapdragonServices/default')]:
        manifest = ET.parse(root / 'vendor/etc/vintf/manifest' / filename).getroot()
        matches = [h for h in manifest.findall('hal') if h.get('format') == 'aidl' and h.findtext('name') == name and h.findtext('fqname') == fqname]
        require(len(matches) == 1, 'provider manifest changed: ' + name)
    node = (root / 'odm/lib64/camera/components/com.qti.node.seg.so').read_bytes()
    require(b'libqsegnet' in node, 'QSegNet loader reference missing')
    parser = elf_dynamic(root / 'vendor/lib64/libopencv_imgproc.so')
    require(parser['soname'] == ['libopencv_imgproc.so'] and 'libopencv_core.so' in parser['needed'], 'current OpenCV pair changed')
    return before, {'camera_files_scanned': len(camera), 'camera_bytes_scanned': sum(i['size'] for i in camera), 'camera_inventory_sha256': inventory_digest(camera), 'old_camera_reference_hits': [], 'perf2_dynamic': dynamic, 'qape_provider_and_stock_policy_verified': True, 'provider_manifests_verified': True}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dump', type=Path, required=True)
    ap.add_argument('--device-tree', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    root = args.dump.resolve()
    out = args.output.resolve()
    require(not out.exists() and not out.is_relative_to(root) and not out.is_relative_to(args.device_tree.resolve()), 'output exists/overlaps inputs')
    repo = Path(__file__).resolve().parents[1]
    profile = json.loads((repo / 'Documentation/xiaomi/annibale-os406-camera-qape-assets.json').read_text())
    text = (args.device_tree / 'proprietary-files.txt').read_text()
    after = convert(text, profile)
    print('Checking all six partitions and pinned camera/provider inputs...', flush=True)
    before, evidence = verify_stock(root, text, profile)
    result = audit(root, after, SUPPORTED_PARTITIONS)
    patch = ''.join(difflib.unified_diff(text.splitlines(True), after.splitlines(True), fromfile='a/proprietary-files.txt', tofile='b/proprietary-files.txt'))
    out.mkdir(parents=True)
    (out / 'proprietary-files.txt').write_text(after)
    (out / 'annibale-os406-camera-qape.patch').write_text(patch)
    (out / 'all-partitions-audit.json').write_text(json.dumps(result, indent=2) + '\n')
    report = {'round': 'R36', 'resolution': 'retire six unused OS4 camera inputs and three legacy standalone QAPE inputs; preserve current stock providers', 'before_counts': before['counts'], 'after_counts': result['counts'], 'input_sha256': sha(text.encode()), 'output_sha256': sha(after.encode()), 'retired_entries': profile['retired_entries'], 'evidence': evidence, 'remaining': [{'source': e['source'], 'section': e['section']} for e in result['entries'] if e['status'] != 'present'], 'policy_changed': False, 'policy_compiled': False, 'runtime_verified': False, 'rom_built': False, 'flashable': False}
    (out / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: pinned migration prepared; ' + json.dumps(result['counts']) + '; runtime unverified')


if __name__ == '__main__':
    main()
