#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check literal local build inputs, not a Soong/Kati or full ROM build.

Blueprint syntax is parsed by the supplied bpfmt. Only literal source-file
properties and LOCAL_PATH/DEVICE_PATH copy inputs are resolved here. Module
references, variable expressions and external Android-tree paths stay unverified.
"""
import argparse
import glob
import hashlib
import json
from pathlib import Path
import re
import subprocess

from prepare_annibale_vendor import tokens

SCALARS = {'src', 'manifest', 'privapp_allowlist'}
ARRAYS = {'srcs', 'init_rc', 'vintf_fragments', 'resource_dirs'}


def blueprint_sources(text):
    ts = [t[0] for t in tokens(text)]
    references, unverified = [], []
    for i, token in enumerate(ts[:-2]):
        if token not in SCALARS | ARRAYS or ts[i+1] != ':':
            continue
        j = i + 2
        if token in SCALARS:
            values = [ts[j]]
            literal = ts[j].startswith('"') and ts[j+1] in (',', '}')
        else:
            if ts[j] != '[':
                unverified.append({'property': token, 'reason': 'nonliteral expression'})
                continue
            end = j + 1
            while end < len(ts) and ts[end] != ']':
                end += 1
            values = [v for v in ts[j+1:end] if v != ',']
            literal = all(v.startswith('"') for v in values) and end+1 < len(ts) and ts[end+1] in (',', '}')
        if not literal:
            unverified.append({'property': token, 'reason': 'nonliteral expression'})
            continue
        for value in values:
            value = json.loads(value)
            if value.startswith((':', '//')):
                unverified.append({'property': token, 'value': value, 'reason': 'module reference'})
            else:
                references.append((token, value))
    return references, unverified


def resolve(root, directory, value):
    root = root.resolve()
    if not value or Path(value).is_absolute():
        return [], 'absolute/empty local source'
    candidate = directory / value
    if not candidate.resolve().is_relative_to(root):
        return [], 'source escapes checked tree'
    matches = sorted(Path(p) for p in glob.glob(str(candidate), recursive=True))
    if any(not p.resolve().is_relative_to(root) for p in matches):
        return [], 'source symlink escapes checked tree'
    if not matches:
        return [], 'missing local source'
    return matches, None


def check(root, bpfmt):
    root = root.resolve()
    records, errors, unverified, parsed = [], [], [], []
    for bp in sorted(root.rglob('Android.bp')):
        proc = subprocess.run([str(bpfmt), '-o', str(bp)], capture_output=True, text=True)
        if proc.returncode:
            errors.append({'file': str(bp.relative_to(root)), 'reason': 'Blueprint parse failed', 'detail': proc.stderr})
            continue
        parsed.append(str(bp.relative_to(root)))
        refs, skipped = blueprint_sources(bp.read_text())
        unverified.extend({'file': str(bp.relative_to(root)), **r} for r in skipped)
        for prop, value in refs:
            paths, error = resolve(root, bp.parent, value)
            record = {'file': str(bp.relative_to(root)), 'property': prop, 'source': value,
                      'matches': [str(p.relative_to(root)) for p in paths]}
            records.append(record)
            if error:
                errors.append({**record, 'reason': error})
    # Only literal copy sources rooted at the checked device's LOCAL_PATH or
    # DEVICE_PATH. Other make expressions are intentionally not evaluated.
    for mk in sorted(root.rglob('*.mk')):
        text = '\n'.join(line.split('#', 1)[0] for line in mk.read_text().splitlines())
        for value in re.findall(r'\$\((?:LOCAL_PATH|DEVICE_PATH)\)/([^\s:]+):', text):
            if '$' in value:
                unverified.append({'file': str(mk.relative_to(root)), 'value': value, 'reason': 'make expression'})
                continue
            paths, error = resolve(root, root, value)
            record = {'file': str(mk.relative_to(root)), 'property': 'copy_source', 'source': value,
                      'matches': [str(p.relative_to(root)) for p in paths]}
            records.append(record)
            if error:
                errors.append({**record, 'reason': error})
    return {'status': 'blocked' if errors else 'scoped_local_inputs_passed',
            'blueprints_parsed': parsed, 'references_checked': records, 'errors': errors,
            'unverified_references': unverified, 'full_rom_built': False,
            'scope': 'Literal local file inputs and Blueprint syntax only; no module/dependency/type resolution',
            'bpfmt_sha256': hashlib.sha256(bpfmt.read_bytes()).hexdigest()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree', type=Path, required=True)
    ap.add_argument('--bpfmt', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    args = ap.parse_args()
    report = check(args.tree, args.bpfmt.resolve())
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(report['status'], len(report['references_checked']), 'local references;', len(report['errors']), 'errors')
    return int(bool(report['errors']))


if __name__ == '__main__':
    raise SystemExit(main())
