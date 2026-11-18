#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Audit a proprietary extraction list against an unpacked stock dump, read-only.

Source paths, destination paths and generated SYMLINK owners are distinct. Only
vendor and odm are qualified here. A complete path inventory is not HAL/ELF ABI,
VINTF, firmware authenticity, generated-vendor correctness or boot qualification.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

PARTITIONS = {'vendor', 'odm'}


def deduplicate_entries(text):
    """Remove only identical entries, retaining the first line and all comments."""
    seen, output, removed = {}, [], []
    for number, raw in enumerate(text.splitlines(True), 1):
        line = raw.strip()
        if line and not line.startswith('#'):
            if line in seen:
                removed.append({'line': number, 'first_line': seen[line], 'entry': line})
                continue
            seen[line] = number
        output.append(raw)
    result = ''.join(output)
    # Conflicting remaps/flags and generated link owners are not duplicates that
    # can safely be discarded. Reject them rather than choosing an arbitrary one.
    parse_list(result)
    return result, removed


def safe_path(value):
    parts = value.split('/')
    if not value or value.startswith('/') or any(p in ('', '.', '..') for p in parts):
        raise ValueError('unsafe Android path: ' + value)
    return value


def parse_list(text):
    entries, owners = [], {}
    section = ''
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith('#'):
            section = line[1:].strip()
            continue
        if any(c.isspace() for c in line):
            raise ValueError(f'unsupported whitespace in entry {number}')
        content, *pins = line.split('|')
        if len(pins) > 2 or any(not re.fullmatch('[0-9a-fA-F]{40}', p) for p in pins):
            raise ValueError(f'invalid SHA-1 pin at line {number}')
        paths, *flags = content.removeprefix('-').split(';')
        paths = paths.split(':')
        if len(paths) > 2:
            raise ValueError(f'multiple destinations at line {number}')
        src, dst = safe_path(paths[0]), safe_path(paths[-1])
        links = []
        for flag in flags:
            if not flag:
                raise ValueError(f'empty flag at line {number}')
            if flag.startswith('SYMLINK='):
                links.extend(safe_path(p) for p in flag.split('=', 1)[1].split(','))
        for owner in [dst] + links:
            if owner in owners:
                raise ValueError(f'duplicate destination {owner}: lines {owners[owner]} and {number}')
            owners[owner] = number
        entries.append({'line': number, 'section': section, 'source': src,
                        'destination': dst, 'flags': flags, 'symlinks': links,
                        'source_sha1_pin': pins[0].lower() if pins else None,
                        'fixup_sha1_pin': pins[1].lower() if len(pins) == 2 else None})
    if not entries:
        raise ValueError('empty proprietary list')
    return entries


def resolve_android(root, name):
    """Resolve extracted Android links without following absolute links on host."""
    pending = safe_path(name).split('/')
    resolved, links = [], []
    while pending:
        part = pending.pop(0)
        if part in ('', '.'):
            continue
        if part == '..':
            if not resolved:
                raise ValueError('symlink escapes Android root')
            resolved.pop()
            continue
        resolved.append(part)
        path = root.joinpath(*resolved)
        if not path.is_symlink():
            continue
        target = os.readlink(path)
        links.append({'path': '/'.join(resolved), 'target': target})
        if len(links) > 40:
            raise ValueError('symlink loop/limit')
        resolved.pop()
        if target.startswith('/'):
            resolved = []
        pending = target.split('/') + pending
    return '/'.join(resolved), links


def file_hashes(path):
    sha1, sha256 = hashlib.sha1(), hashlib.sha256()
    with path.open('rb') as stream:
        while data := stream.read(1024 * 1024):
            sha1.update(data); sha256.update(data)
    return {'size': path.stat().st_size, 'sha1': sha1.hexdigest(), 'sha256': sha256.hexdigest()}


def audit(root, text):
    root = root.resolve()
    for part in PARTITIONS:
        if not (root / part).is_dir() or (root / part).is_symlink():
            raise ValueError('supply real extracted partition directory: ' + part)
    result, hashes = [], {}
    for entry in parse_list(text):
        item = dict(entry)
        if entry['source'].split('/')[0] not in PARTITIONS:
            item['status'] = 'outside_scope'
            result.append(item)
            continue
        resolved, links = resolve_android(root, entry['source'])
        item.update(resolved_source=resolved, source_links=links)
        path = root / resolved
        if resolved.split('/')[0] not in PARTITIONS:
            item['status'] = 'external_symlink_unverified'
        elif not path.exists():
            item['status'] = 'missing'
        elif not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError('not a regular blob: ' + resolved)
        else:
            if resolved not in hashes:
                hashes[resolved] = file_hashes(path)
            item.update(hashes[resolved])
            pin = entry['source_sha1_pin']
            item['status'] = 'source_pin_mismatch' if pin and pin != item['sha1'] else 'present'
        result.append(item)
    counts = dict(Counter(e['status'] for e in result))
    blocked = any(counts.get(s, 0) for s in ('missing', 'source_pin_mismatch', 'external_symlink_unverified'))
    return {'schema_version': 1,
            'status': 'incomplete_vendor_odm_inputs' if blocked else 'vendor_odm_paths_present',
            'list_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'scope': sorted(PARTITIONS), 'counts': counts, 'entries': result,
            'generated_vendor_built': False, 'hal_abi_verified': False, 'hardware_tested': False,
            'unverified': ['Unselected partitions and source-provided components',
                           'Blob fixups, ELF dependency namespaces and HAL/VINTF ABI',
                           'Image provenance, firmware signature and SELinux/runtime behavior']}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dump', type=Path, required=True)
    ap.add_argument('--proprietary-files', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    args = ap.parse_args()
    result = audit(args.dump, args.proprietary_files.read_text())
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(result['status'] + ': ' + json.dumps(result['counts'], sort_keys=True))
    return 0 if result['status'] == 'vendor_odm_paths_present' else 1


if __name__ == '__main__':
    raise SystemExit(main())
