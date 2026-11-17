#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare a narrow generated-vendor ownership patch without copying blobs.

The input is never modified. A successful patch is not a firmware or HAL match.
Only the reviewed standalone sh_binary and PRODUCT_PACKAGES layout is accepted.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import subprocess

from annibale_ramdisk import require

LOADERS = ('system_dlkm_modprobe', 'vendor_modprobe')
TOKEN = re.compile(r'\s+|//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|[A-Za-z_][A-Za-z_0-9]*|.', re.S)


def tokens(text):
    return [(m.group(), m.start(), m.end()) for m in TOKEN.finditer(text)
            if not (m.group().isspace() or m.group().startswith(('//', '/*')))]


def blocks(text):
    """Locate top-level Blueprint modules; ignore braces inside strings/comments."""
    ts = tokens(text)
    depth, start = 0, None
    for i, (token, begin, end) in enumerate(ts):
        if token == '{':
            if depth == 0:
                require(i > 0 and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', ts[i-1][0]),
                        'unsupported top-level Blueprint object')
                start = i-1
            depth += 1
        elif token == '}':
            depth -= 1
            require(depth >= 0, 'unbalanced Blueprint braces')
            if depth == 0:
                yield ts[start][0], ts[start][1], end, ts[start:i+1]
    require(depth == 0, 'unbalanced Blueprint braces')


def scalar_properties(ts):
    """Selected loaders have only scalar properties; reject extensions for review."""
    values, i = {}, 2
    while i < len(ts)-1:
        require(i+3 < len(ts) and ts[i+1][0] == ':' and ts[i+3][0] == ',',
                'unsupported loader property layout')
        name, value = ts[i][0], ts[i+2][0]
        require(name not in values, 'duplicate loader property')
        if value.startswith('"'):
            value = json.loads(value)
        else:
            require(value in ('true', 'false'), 'nonliteral loader property')
            value = value == 'true'
        values[name] = value
        i += 4
    return values


def convert(bp, product):
    removals, owners = [], {}
    for kind, begin, end, ts in blocks(bp):
        strings = {json.loads(t[0]) for t in ts if t[0].startswith('"')}
        hits = [n for n in LOADERS if strings & {n, n+'.sh', 'proprietary/vendor/bin/'+n+'.sh'}]
        if not hits:
            continue
        require(len(hits) == 1 and kind == 'sh_binary', 'unexpected loader owner/type')
        name = hits[0]
        require(name not in owners, 'duplicate installed loader owner: '+name)
        props = scalar_properties(ts)
        require(set(props) <= {'name','owner','src','filename','soc_specific','vendor'},
                'unreviewed loader properties')
        require(props.get('name') == name and props.get('src') == 'proprietary/vendor/bin/'+name+'.sh'
                and props.get('filename') == name+'.sh', 'loader name/source/destination changed')
        require(props.get('soc_specific') is True or props.get('vendor') is True,
                'loader must install in vendor')
        owners[name] = props
        # Remove only this module, not adjacent comments or other generated owners.
        removals.append((begin, end))
    require(set(owners) == set(LOADERS), 'expected both extracted loader owners')
    new_bp = bp
    for begin, end in reversed(removals):
        new_bp = new_bp[:begin] + new_bp[end:]
    lines = product.splitlines(True)
    current = None
    counts = {n: 0 for n in LOADERS}
    new_lines = []
    for line in lines:
        assignment = re.match(r'^([A-Z_]+)\s*(?::=|\+=|=)', line)
        if assignment:
            current = assignment.group(1)
        stripped = line.strip()
        words = stripped.removesuffix('\\').strip().split()
        selected = set(words) & set(LOADERS)
        if selected:
            require(current == 'PRODUCT_PACKAGES' and len(words) == 1 and stripped.endswith('\\')
                    and line[:1].isspace(), 'unsupported loader package entry')
            counts[words[0]] += 1
        else:
            new_lines.append(line)
        if stripped and not stripped.startswith('#') and not stripped.endswith('\\'):
            current = None
    require(all(c == 1 for c in counts.values()), 'missing/duplicate loader product package')
    new_product = ''.join(new_lines)
    for name in LOADERS:
        require(name+'.sh' not in new_bp and name+'.sh' not in new_product,
                'another loader file owner remains')
    return new_bp, new_product, owners


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--vendor', type=Path, required=True)
    ap.add_argument('--expected-commit', required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    root, output = args.vendor.resolve(), args.output.resolve()
    head = subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'], text=True).strip()
    require(head == args.expected_commit, 'vendor reference commit changed')
    require(not subprocess.check_output(['git','-C',str(root),'status','--porcelain']), 'vendor reference must be clean')
    require(not output.exists() and root not in output.parents and output not in root.parents,
            'output exists or overlaps vendor reference')
    before = {name:(root/name).read_text() for name in ('Android.bp','annibale-vendor.mk')}
    bp, mk, owners = convert(before['Android.bp'], before['annibale-vendor.mk'])
    after = {'Android.bp':bp,'annibale-vendor.mk':mk}
    patch = ''.join(''.join(difflib.unified_diff(before[n].splitlines(True), after[n].splitlines(True),
                    fromfile='a/'+n, tofile='b/'+n)) for n in before)
    output.mkdir(parents=True)
    (output/'annibale-vendor-conversion.patch').write_text(patch)
    sha = lambda text: hashlib.sha256(text.encode()).hexdigest()
    report = {'status':'vendor_patch_prepared','vendor_reference_commit':head,
              'firmware_match_verified':False,'rom_built':False,'removed_owners':owners,
              'files':{n:{'before_sha256':sha(before[n]),'after_sha256':sha(after[n])} for n in before},
              'patch_sha256':sha(patch),
              'unverified':['Exact OS4 vendor provenance and binary/HAL ABI','Full Android module namespace and image ownership','Runtime init, firmware and enforcing SELinux']}
    (output/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: two extracted loader owners and product entries removed in patch; vendor input unchanged')


if __name__ == '__main__':
    main()
