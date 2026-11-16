#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Audit retained OEM normal-boot providers, never claim flash readiness."""
import argparse
from collections import defaultdict
import json
from pathlib import Path

from audit_annibale_stock import audit, compare, digest, exports, magic_flags
from verify_annibale_modules import module_info, read_symvers


def normal_paths(record):
    return [p for p in record['paths'] if p.startswith((
        'vendor_boot/lib/modules/', 'vendor_dlkm/lib/modules/',
        'system_dlkm/lib/modules/'))]


def select(records, early_names):
    """Only two explicitly evidenced first-stage ownership exceptions exist."""
    groups = defaultdict(list)
    for record in records:
        paths = normal_paths(record)
        if paths:
            groups[record['name']].append(dict(record, paths=paths))
    selected, ownership, errors = {}, [], []
    for name, variants in sorted(groups.items()):
        if len(variants) == 1:
            selected[name] = variants[0]
            continue
        early = [r for r in variants if any(
            p.startswith('vendor_boot/') for p in r['paths'])]
        late = [r for r in variants if all(
            p.startswith('system_dlkm/') for p in r['paths'])]
        if (name in {'zram', 'zsmalloc'} and name in early_names
                and len(variants) == 2 and len(early) == len(late) == 1):
            selected[name] = early[0]
            ownership.append({'name': name, 'selected_sha256': early[0]['sha256'],
                              'later_sha256': late[0]['sha256'],
                              'condition': 'vendor_boot first-stage load succeeds before system_dlkm'})
        else:
            errors.append({'name': name, 'reason': 'unresolved normal-boot variants',
                           'sha256': [r['sha256'] for r in variants]})
    return selected, ownership, errors


def load_names(path):
    return [Path(line.split('#', 1)[0].strip()).stem.replace('-', '_')
            for line in path.read_text().splitlines() if line.split('#', 1)[0].strip()]


def run(stock, kernel):
    inventory = audit(stock, kernel)
    early_list = stock / 'vendor_boot/lib/modules/modules.load'
    early = load_names(early_list)
    selected, ownership, errors = select(inventory['modules'], early)
    symbols = read_symvers([kernel / 'Module.symvers'])
    providers, imports, details = defaultdict(list), {}, []
    for name, record in selected.items():
        path = stock / record['paths'][0]
        info, imports[name] = module_info(path)
        for symbol, crc in exports(path).items():
            providers[symbol].append((name, crc))
    duplicates = {s: [p[0] for p in entries] for s, entries in providers.items()
                  if len(entries) > 1}
    early_closure, pending = set(), list(early)
    early_failures = []
    while pending:
        name = pending.pop()
        if name in early_closure:
            continue
        early_closure.add(name)
        record = selected.get(name)
        if record is None:
            early_failures.append({'module': name, 'reason': 'missing provider'})
            continue
        if not any(p.startswith('vendor_boot/') for p in record['paths']):
            early_failures.append({'module': name, 'reason': 'requires later partition'})
        pending.extend(record['depends'])
        for symbol in imports[name]:
            if symbol in symbols and symbols[symbol][1] == 'vmlinux':
                continue
            pending.extend(p[0] for p in providers.get(symbol, []))
    for name, record in selected.items():
        checked = compare(imports[name], providers, symbols)
        checked.update(name=name, sha256=record['sha256'], paths=record['paths'],
                       missing_dependencies=sorted(set(record['depends']) - selected.keys()),
                       duplicate_builtin_exports=record['duplicate_builtin_exports'],
                       vermagic_flags_match=magic_flags(record['vermagic']) ==
                       magic_flags(inventory['kernel']['vermagic']))
        checked['blocked'] = any(checked[k] for k in (
            'kernel_crc_mismatches', 'missing_symbols', 'stock_provider_crc_mismatches',
            'missing_dependencies', 'duplicate_builtin_exports')) or not checked['vermagic_flags_match']
        details.append(checked)
    blocked = bool(errors or inventory['invalid_modules'] or duplicates or early_failures
                   or any(r['blocked'] for r in details))
    return {'schema_version': 1, 'status': 'blocked' if blocked else 'conditional_abi_pass',
            'flash_ready': False,
            'scope': 'Available retained OEM normal-boot providers; not all modules are loaded',
            'kernel': inventory['kernel'], 'all_inventory_variants_unchanged':
            inventory['ambiguous_module_variants'],
            'selected_names': len(selected), 'conditional_first_stage_ownership': ownership,
            'selection_errors': errors, 'invalid_modules': inventory['invalid_modules'],
            'duplicate_selected_exports': duplicates,
            'first_stage': {'load_list_sha256': digest(early_list), 'roots': len(early),
                            'hard_dependency_closure': sorted(early_closure),
                            'failures': early_failures},
            'modules_with_detected_blockers': sum(r['blocked'] for r in details),
            'modules': details,
            'unverified': ['Actual first-stage success and OEM duplicate-load behavior',
                           'Soft dependencies, parameters, namespaces, licenses and probe order',
                           'Signature trust, CFI and runtime structure compatibility',
                           'Live userdata filesystem and verified boot policy',
                           'Native ROM: source module integration remains a separate candidate',
                           'Hardware operation and recovery path']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock', type=Path, required=True)
    parser.add_argument('--kernel-out', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = run(args.stock, args.kernel_out)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('status', 'selected_names',
                                           'modules_with_detected_blockers', 'flash_ready')}))
    return int(report['status'] == 'blocked')


if __name__ == '__main__':
    raise SystemExit(main())
