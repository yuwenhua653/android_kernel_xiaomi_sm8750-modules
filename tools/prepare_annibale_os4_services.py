#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare pinned OS4 MiNet/SLA, WFD parser and IMS extraction migration.

Writes a reviewable device-tree patch; does not modify stock, compile policy,
qualify hardware or enable the experimental SLA kernel module.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from annibale_ramdisk import require
from audit_annibale_vendor_blobs import parse_list, safe_path
from prepare_annibale_os4_userspace import elf_dynamic


def digest(data):
    return hashlib.sha256(data).hexdigest()


def convert(before, profile, templates):
    for name, expected in profile['input_sha256'].items():
        require(digest(before[name].encode()) == expected, 'unreviewed input: '+name)
    after = dict(before)
    text = before['proprietary-files.txt']
    lines = text.splitlines()
    entries = parse_list(text)
    owners = {p for e in entries for p in [e['source'],e['destination']]+e['symlinks']}
    for old, new in profile['relocations'].items():
        require(lines.count(old) == 1 and new not in owners, 'relocation owner conflict: '+old)
    additions = [n for group in profile['add_after'].values() for n in group]
    require(len(additions) == len(set(additions)), 'duplicate additions')
    for name in additions:
        require(name not in owners, 'added owner conflict: '+name)
    for name in profile['retired_entries'] + profile['retained_entries'] + list(profile['add_after']):
        require(lines.count(name) == 1, 'changed required entry: '+name)
    result = []
    for line in lines:
        if line not in profile['retired_entries']:
            result.append(profile['relocations'].get(line,line))
        result.extend(profile['add_after'].get(line,[]))
    after['proprietary-files.txt'] = '\n'.join(result)+'\n'
    parse_list(after['proprietary-files.txt'])
    change = profile['context_replacement']
    lines = before[change['file']].splitlines()
    require(lines.count(change['old']) == 1, 'changed executable context')
    require(change['new'].split()[0] not in {l.split()[0] for l in lines if l.strip()}, 'new executable context already owned')
    after[change['file']] = '\n'.join(change['new'] if l==change['old'] else l for l in lines)+'\n'
    for name, addition in profile['append'].items():
        old_owners={l.split()[0] for l in after[name].splitlines() if l.strip() and not l.lstrip().startswith('#')}
        new_owners=[l.split()[0] for l in addition.splitlines() if l.strip()]
        require(not old_owners.intersection(new_owners) and len(new_owners)==len(set(new_owners)), 'duplicate policy context: '+name)
        after[name]=after[name].rstrip()+'\n\n# OS4 merged MiNet/SLA service\n'+addition
    for name, item in profile['new_files'].items():
        require(name not in before, 'policy file already exists: '+name)
        data=templates[name]
        require(digest(data.encode()) == item['sha256'], 'changed policy template: '+name)
        after[name]=data
    return after


def verify_assets(root, profile):
    root=root.resolve()
    require(profile['firmware_label']=='OS4.0.6.0.XPKCNXM','wrong firmware profile')
    for part, rel in [('vendor','build.prop'),('odm','etc/build.prop')]:
        p=root/part/rel
        require(p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root), 'unsafe build property')
        require(p.read_text().splitlines().count(f'ro.{part}.build.version.incremental='+profile['incremental'])==1,'wrong stock build')
    for name, item in profile['files'].items():
        p=root/safe_path(name)
        require(p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root),'missing/unsafe asset: '+name)
        require(p.stat().st_size==item['size'] and digest(p.read_bytes())==item['sha256'],'changed asset: '+name)
    for name in list(profile['relocations']) + [x.split(';')[0] for x in profile['retired_entries']]:
        p=root/safe_path(name)
        require(not p.exists() and not p.is_symlink(),'old asset unexpectedly present: '+name)
    dynamic={}
    for name, required in profile['required_dependencies'].items():
        dynamic[name]=elf_dynamic(root/name)
        require(set(required)<=set(dynamic[name]['needed']),'changed consumer: '+name)
    parser=elf_dynamic(root/'system_ext/lib64/libwfdparserlite.so')
    require(parser['soname']==['libwfdparserlite.so'],'wrong WFD parser SONAME')
    with ZipFile(root/'system_ext/priv-app/ims/ims.apk') as archive:
        dex=[archive.read(n) for n in archive.namelist() if n.endswith('.dex')]
    require(bool(dex),'IMS APK has no DEX')
    for value in profile['ims_dex_required_strings']:
        require(any(value.encode() in d for d in dex),'missing IMS replacement evidence: '+value)
    for value in profile['ims_dex_forbidden_strings']:
        require(not any(value.encode() in d for d in dex),'old IMS JNI still referenced')
    cil=(root/'vendor/etc/selinux/vendor_sepolicy.cil').read_text()
    require('(typeattributeset hal_slaaidlservice_server (hal_slaaidlservice_default hal_minetaidlservice_default))' in cil,'stock merged SLA server ownership changed')
    return {'consumer_elf':dynamic,'parser_elf':parser,'ims_camera2_and_media_tokens_verified':True,'stock_merged_sla_policy_owner_verified':True}


def verify_manifest(text, required):
    root=ET.fromstring(text)
    for name, fqname in required.items():
        matches=[h for h in root.findall('hal') if h.get('format')=='aidl' and h.findtext('name')==name and h.findtext('fqname')==fqname]
        require(len(matches)==1, 'missing/duplicate AIDL instance: '+name)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dump',type=Path,required=True)
    ap.add_argument('--device-tree',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    repo=Path(__file__).resolve().parents[1]
    profile=json.loads((repo/'Documentation/xiaomi/annibale-os406-services-assets.json').read_text())
    evidence=verify_assets(args.dump,profile)
    before={n:(args.device_tree/safe_path(n)).read_text() for n in profile['input_sha256']}
    for n in profile['new_files']:
        require(not (args.device_tree/n).exists() and not (args.device_tree/n).is_symlink(),'new policy target exists: '+n)
    templates={n:(repo/safe_path(v['template'])).read_text() for n,v in profile['new_files'].items()}
    verify_manifest(before['vintf/manifest.xml'],profile['required_aidl_instances'])
    after=convert(before,profile,templates)
    out=args.output.resolve()
    require(not out.exists() and not out.is_relative_to(args.dump.resolve()) and not out.is_relative_to(args.device_tree.resolve()),'output exists/overlaps inputs')
    patch=''
    for n,text in after.items():
        if text==before.get(n):continue
        patch+=''.join(difflib.unified_diff(before.get(n,'').splitlines(True),text.splitlines(True),fromfile='a/'+n if n in before else '/dev/null',tofile='b/'+n))
    out.mkdir(parents=True)
    for n,text in after.items():
        p=out/'tree'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    (out/'annibale-os406-services.patch').write_text(patch)
    report={'status':'pinned_service_migration_prepared','input_sha256':profile['input_sha256'],
            'output_sha256':{n:digest(t.encode()) for n,t in after.items()},'evidence':evidence,
            'relocations':profile['relocations'],'retired_entries':profile['retired_entries'],
            'added_entries':[n for group in profile['add_after'].values() for n in group],
            'policy_compiled':False,'rom_built':False,'runtime_verified':False,'experimental_sla_module_enabled':False}
    (out/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: 3 input replacements, 1 obsolete IMS JNI entry retired, 4 support inputs and scoped policy prepared; runtime unverified')


if __name__=='__main__':
    main()
