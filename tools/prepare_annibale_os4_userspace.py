#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare pinned OS4 camera/display/WFD/ATFWD extraction inputs and fixups.

No stock file is modified. This does not qualify generated vendor, Android ABI,
SELinux or hardware. Run against the R31 converted reference and matching dump.
"""
import argparse
import ast
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from annibale_ramdisk import require
from audit_annibale_vendor_blobs import parse_list, safe_path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def replacement_rules(script, name):
    """Read a selected declarative blob-fixup chain without executing the script."""
    tree=ast.parse(script)
    dictionaries=[n.value for n in tree.body if isinstance(n,ast.AnnAssign)
                  and isinstance(n.target,ast.Name) and n.target.id == 'blob_fixups']
    require(len(dictionaries)==1 and isinstance(dictionaries[0],ast.Dict), 'changed blob fixup dictionary')
    values=[]
    for key, value in zip(dictionaries[0].keys,dictionaries[0].values):
        keys=ast.literal_eval(key)
        if name in ((keys,) if isinstance(keys,str) else keys):values.append(value)
    require(len(values)==1, 'missing/duplicate fixup owner: '+name)
    rules=[];node=values[0]
    while isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
        require(node.func.attr == 'replace_needed' and not node.keywords, 'unreviewed selected fixup')
        args=[ast.literal_eval(a) for a in node.args]
        require(len(args)==2 and all(isinstance(a,str) for a in args), 'changed replacement operands')
        rules.append(args);node=node.func.value
    require(isinstance(node,ast.Call) and isinstance(node.func,ast.Name)
            and node.func.id=='blob_fixup' and not node.args and not node.keywords, 'changed fixup constructor')
    return list(reversed(rules))


def elf_dynamic(path):
    with path.open('rb') as stream:
        require(stream.read(6) == b'\x7fELF\x02\x01', 'expected ELF64 little-endian: '+str(path))
    output = subprocess.check_output(['readelf','--wide','--dynamic',str(path)],
                                     text=True, env=dict(os.environ, LC_ALL='C'))
    return {'needed':re.findall(r'\(NEEDED\).*?\[(.*?)\]',output),
            'soname':re.findall(r'\(SONAME\).*?\[(.*?)\]',output)}


def convert(files, profile):
    for name, expected in profile['input_sha256'].items():
        require(digest(files[name].encode()) == expected, 'unreviewed input: '+name)
    result = dict(files)
    text = files['proprietary-files.txt']
    entries = parse_list(text)
    owners = {p for e in entries for p in [e['source'],e['destination']]+e['symlinks']}
    for old, new in profile['relocations'].items():
        require(text.splitlines().count(old) == 1 and new not in owners, 'changed relocation owner')
    after = []
    for line in text.splitlines():
        after.append(profile['relocations'].get(line,line))
        for new, anchor in profile['add_after'].items():
            require(new not in owners and text.splitlines().count(anchor) == 1, 'changed added owner')
            if line == anchor:
                after.append(new)
    result['proprietary-files.txt'] = '\n'.join(after)+'\n'
    parse_list(result['proprietary-files.txt'])
    script = files['extract-files.py']
    # Extend existing reviewed fixup groups, without replacing whole dictionaries
    # or introducing a second key that would shadow a previous fixup.
    edits = {
        "        'odm/lib64/libcom.xiaomi.grallocutils.so',\n":
        "        'odm/lib64/libcameraopt_stub.so',\n        'odm/lib64/libcom.xiaomi.grallocutils.so',\n",
        "        'odm/lib64/libdither.so',\n":
        "        'odm/lib64/libdither.so',\n        'odm/lib64/libdynamicelvss.so',\n",
    }
    for old, new in edits.items():
        require(script.count(old) == 1, 'changed fixup group anchor')
        script = script.replace(old,new)
    ast.parse(script)
    for name, replacements in profile['fixups'].items():
        require(replacement_rules(script,name) == [list(pair) for pair in replacements.items()],
                'generated fixup chain differs: '+name)
    result['extract-files.py'] = script
    return result


def verify_assets(root, profile):
    root = root.resolve()
    require(profile['firmware_label'] == 'OS4.0.6.0.XPKCNXM', 'wrong firmware profile')
    for part, rel in (('vendor','build.prop'),('odm','etc/build.prop')):
        path=root/part/rel
        require(not path.is_symlink() and path.resolve().is_relative_to(root), 'unsafe properties')
        require(path.read_text().splitlines().count(
            f'ro.{part}.build.version.incremental='+profile['incremental']) == 1, 'wrong stock build')
    for name, item in profile['files'].items():
        path=root/safe_path(name)
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root), 'unsafe/missing asset: '+name)
        require(path.stat().st_size == item['size'] and digest(path.read_bytes()) == item['sha256'], 'changed asset: '+name)
    for name in profile['relocations']:
        path=root/safe_path(name)
        require(not path.exists() and not path.is_symlink(), 'old asset unexpectedly present: '+name)
    evidence={}
    for name, dependencies in profile['required_dependencies'].items():
        dynamic=elf_dynamic(root/name)
        require(set(dependencies) <= set(dynamic['needed']), 'consumer dependency changed: '+name)
        evidence[name]=dynamic
    for name, replacements in profile['fixups'].items():
        dynamic=elf_dynamic(root/name)
        require(set(replacements) <= set(dynamic['needed']), 'fixup input dependency changed: '+name)
        require(dynamic['soname'] == [Path(name).name], 'unexpected added library SONAME')
        evidence[name]=dynamic
    new=profile['relocations']['system_ext/lib64/vendor.qti.hardware.wifidisplaysession_aidl-V1-ndk.so']
    dynamic=elf_dynamic(root/new)
    require(dynamic['soname'] == [Path(new).name], 'unexpected WFD V2 SONAME')
    evidence[new]=dynamic
    return evidence


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dump',type=Path,required=True)
    ap.add_argument('--device-tree',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    repo=Path(__file__).resolve().parents[1]
    profile=json.loads((repo/'Documentation/xiaomi/annibale-os406-userspace-assets.json').read_text())
    evidence=verify_assets(args.dump,profile)
    before={name:(args.device_tree/name).read_text() for name in profile['input_sha256']}
    after=convert(before,profile)
    output=args.output.resolve()
    require(not output.exists() and not output.is_relative_to(args.dump.resolve())
            and not output.is_relative_to(args.device_tree.resolve()), 'output exists/overlaps inputs')
    patch=''.join(''.join(difflib.unified_diff(before[n].splitlines(True),after[n].splitlines(True),
                  fromfile='a/'+n,tofile='b/'+n)) for n in before)
    output.mkdir(parents=True)
    for name, text in after.items(): (output/name).write_text(text)
    (output/'annibale-os406-userspace.patch').write_text(patch)
    report={'status':'pinned_userspace_patch_prepared','input_sha256':profile['input_sha256'],
            'output_sha256':{n:digest(t.encode()) for n,t in after.items()},'assets':profile['files'],
            'dynamic_dependencies':evidence,'relocations':profile['relocations'],
            'added_libraries':list(profile['add_after']),'fixups':profile['fixups'],
            'stock_modified':False,'generated_vendor_built':False,'rom_built':False,'hardware_tested':False}
    (output/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: OS4 userspace inputs/fixup patch prepared; full ABI/runtime unverified')


if __name__ == '__main__':
    main()
