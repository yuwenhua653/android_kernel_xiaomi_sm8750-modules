#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check scoped native loader service ownership and firmware search wiring.

This is a source-text contract, not Android init parsing, HAL ABI or SELinux
compilation. It never starts services, loads firmware or changes a vendor tree.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex

from annibale_ramdisk import require
from build_annibale_native_images import check_fstab
from prepare_annibale_rom_handoff import LOADER_RUNTIME_PACKAGES

SERVICES = {'gki.modprobe':'system_dlkm_modprobe.sh', 'vendor.modprobe':'vendor_modprobe.sh'}


def logical_lines(text):
    pending = ''
    for line in text.splitlines():
        if not pending and line.lstrip().startswith('#'):
            continue
        # Android init supports backslash-newline continuation before tokenization.
        continued = len(line) - len(line.rstrip('\\'))
        if continued % 2:
            pending += line[:-1] + ' '
            continue
        yield pending + line
        pending = ''
    require(not pending, 'unterminated init continuation')


def sections(text):
    current = None
    for line in logical_lines(text):
        words = shlex.split(line, comments=True)
        if not words:
            continue
        if not line[0].isspace():
            if current is not None:
                yield current
            current = {'head':words,'body':[]}
        else:
            require(current is not None, 'init command outside a section')
            current['body'].append(words)
    if current is not None:
        yield current


def check_services(files):
    parsed = [(name, section) for name, text in files.items() for section in sections(text)]
    owners = {}
    for service, script in SERVICES.items():
        matches = [(n,s) for n,s in parsed if s['head'][:2] == ['service',service]]
        require(len(matches) == 1, 'missing/duplicate init service: '+service)
        name, section = matches[0]
        require(section['head'] == ['service',service,'/vendor/bin/'+script], 'changed loader service executable')
        body = section['body']
        for expected in (['user','root'], ['group','root','system'], ['disabled'], ['oneshot'], ['seclabel','u:r:vendor_modprobe:s0']):
            require(body.count(expected) == 1, 'changed loader service credentials/lifecycle: '+service)
        for option in ('user','group','seclabel'):
            require(sum(bool(v) and v[0] == option for v in body) == 1, 'duplicate service option')
        require(not any(v[0] in ('override','onrestart','reboot_on_failure') for v in body), 'unreviewed loader service behavior')
        owners[service] = name
    starts = [(n,s,i,v) for n,s in parsed for i,v in enumerate(s['body'])
              if len(v)>1 and v[0] in ('start','exec_start','restart') and v[1] in SERVICES]
    require(len(starts) == 2, 'duplicate/missing loader start actions')
    first, second = starts
    require(first[0] == second[0] and first[1] is second[1] and first[1]['head'] == ['on','early-init']
            and first[3] == ['exec_start','gki.modprobe'] and second[3] == ['start','vendor.modprobe']
            and first[2] < second[2], 'loader start ordering changed')
    waits = [(n,s) for n,s in parsed if ['wait_for_prop','vendor.all.modules.ready','1'] in s['body']]
    normal_waits = [(n,s) for n,s in waits if s['head'] == ['on','post-fs-data']]
    require(len(normal_waits) == 1, 'missing/changed normal ready barrier')
    require(all(s['head'] in (['on','post-fs-data'], ['on','init','&&','property:ro.boot.mode=charger']) for n,s in waits),
            'unreviewed ready barrier action')
    require(not any(v[:2] == ['setprop','vendor.all.modules.ready'] for n,s in parsed for v in s['body']),
            'init must not bypass loader readiness')
    return {'service_owners':owners,'start_action':first[0],'ready_barriers':[{'file':n,'trigger':s['head']} for n,s in waits],
            'charger_verified':False}


def check_firmware(ueventd, directories, fstab):
    imports = [shlex.split(l,comments=True) for l in ueventd.splitlines()]
    require(imports.count(['import','/vendor/etc/fw_dir.ueventd.qcom.rc']) == 1, 'firmware search file not imported once')
    paths = [w[1:] for l in directories.splitlines() if (w:=shlex.split(l,comments=True)) and w[0]=='firmware_directories']
    require(len(paths)==1 and set(paths[0]) == {'/vendor/firmware_mnt/image/','/vendor/modem_firmware/image/'},
            'reviewed firmware search directories changed')
    rows = check_fstab(fstab)
    return {'search_paths':paths[0], 'fstab_rows':len(rows), 'firmware_bytes_verified':False}


def check_import(text, target):
    lines = [shlex.split(l,comments=True) for l in logical_lines(text)]
    require(lines.count(['import',target]) == 1, 'missing/duplicate init import: '+target)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--vendor',type=Path,required=True)
    ap.add_argument('--rom',type=Path,required=True)
    ap.add_argument('--handoff',type=Path,required=True)
    ap.add_argument('--report',type=Path,required=True)
    args=ap.parse_args()
    vendor=args.vendor/'proprietary/vendor/etc/init'
    files={str(p.relative_to(vendor)):p.read_text() for p in vendor.rglob('*.rc')}
    require(files, 'missing extracted init files')
    # Include device-owned hw files in duplicate-service detection.
    for p in (args.rom/'rootdir/etc').glob('init*.rc'):
        files['device/'+p.name]=p.read_text()
    result=check_services(files)
    check_import((args.rom/'rootdir/etc/init.qcom.rc').read_text(),'/vendor/etc/init/hw/init.target.rc')
    check_import((args.rom/'rootdir/etc/init.target.rc').read_text(),'/vendor/etc/init/hw/init.qti.kernel.rc')
    check_import((vendor/'hw/init.qti.kernel.rc').read_text(),'/vendor/etc/init/hw/init.qti.kernel.target.rc')
    result['firmware']=check_firmware((args.rom/'rootdir/etc/ueventd.qcom.rc').read_text(),
        (args.rom/'rootdir/etc/fw_dir.ueventd.qcom.rc').read_text(),
        (args.rom/'rootdir/etc/fstab.annibale-oss').read_text())
    packages=(args.handoff/'Product.mk').read_text().split()
    require(set(LOADER_RUNTIME_PACKAGES) <= set(packages), 'missing vendor shell/toolbox/toybox provider')
    result.update(status='scoped_vendor_runtime_passed',runtime_verified=False,rom_built=False,
                  runtime_packages=list(LOADER_RUNTIME_PACKAGES),init_files_checked=len(files),
                  init_sha256={n:hashlib.sha256(t.encode()).hexdigest() for n,t in files.items()})
    args.report.write_text(json.dumps(result,indent=2)+'\n')
    print('PASS: scoped loader services, runtime package selection and firmware search/mount wiring; no device execution')


if __name__=='__main__':
    main()
