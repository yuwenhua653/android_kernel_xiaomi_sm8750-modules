#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Additional retained-OEM loader checks; never certify runtime/flash readiness."""
import argparse
from collections import Counter
import json
import re
from pathlib import Path
import struct
import subprocess

from audit_annibale_normal_boot import load_names, select
from audit_annibale_stock import audit, digest
from verify_annibale_modules import module_info, sections

GPL = {'GPL', 'GPL v2', 'GPL and additional rights', 'Dual BSD/GPL',
       'Dual MIT/GPL', 'Dual MPL/GPL'}
MARKER = b'~Module signature appended~\n'


def cstring(data, offset):
    end = data.find(b'\0', offset)
    if offset < 0 or end < 0:
        raise ValueError('invalid ELF string')
    return data[offset:end].decode('ascii')


def elf_symbols(path):
    parts = sections(path)  # validate ARM64 relocatable ELF and bounds first
    raw = path.read_bytes()
    h = struct.unpack_from('<16sHHIQQQIHHHHHH', raw)
    headers = [struct.unpack_from('<IIQQQQIIQQ', raw, h[6] + i * 64)
               for i in range(h[12])]
    shstr = headers[h[13]]
    names = raw[shstr[4]:shstr[4] + shstr[5]]
    labels = [cstring(names, item[0]) for item in headers]
    result = {}
    for item in headers:
        if item[1] != 2:
            continue
        if item[9] != 24 or item[5] % 24 or item[6] >= len(headers):
            raise ValueError('invalid ELF symbol table')
        strings = parts[labels[item[6]]]
        for offset in range(item[4], item[4] + item[5], 24):
            name, _, _, index, value, _ = struct.unpack_from('<IBBHQQ', raw, offset)
            name = cstring(strings, name)
            if name.startswith(('__ksymtab_', '__kstrtabns_', '__kcfi_typeid_')):
                if name in result:
                    raise ValueError('ambiguous symbol metadata: ' + name)
                result[name] = (index, value)
    return result, labels, parts


def export_policy(symbols, labels, parts):
    result = {}
    for name, (index, _) in symbols.items():
        if not name.startswith('__ksymtab_'):
            continue
        symbol = name[len('__ksymtab_'):]
        if index >= len(labels) or labels[index] not in ('__ksymtab', '__ksymtab_gpl'):
            raise ValueError('unknown export class: ' + symbol)
        ns = symbols.get('__kstrtabns_' + symbol)
        if ns is None or ns[0] >= len(labels):
            raise ValueError('missing export namespace metadata: ' + symbol)
        result[symbol] = {'gpl_only': labels[index] == '__ksymtab_gpl',
                          'namespace': cstring(parts[labels[ns[0]]], ns[1])}
    return result


def signature(raw):
    if not raw.endswith(MARKER):
        return {'status': 'unsigned'}
    end = len(raw) - len(MARKER)
    if end <= 12:
        raise ValueError('truncated module signature header')
    fields = struct.unpack('>8BI', raw[end - 12:end])
    size = fields[-1]
    if size == 0 or size >= end - 12:
        raise ValueError('invalid module signature length')
    if fields[2] != 2 or any(fields[i] for i in (0, 1, 3, 4, 5, 6, 7)):
        raise ValueError('unsupported or malformed module signature header')
    der = raw[end - 12 - size:end - 12]
    proc = subprocess.run(['openssl', 'cms', '-inform', 'DER', '-cmsout', '-noout'],
                          input=der, capture_output=True, timeout=15)
    if proc.returncode:
        raise ValueError('unparseable PKCS7/CMS signature')
    return {'status': 'pkcs7_syntax_checked_trust_unverified', 'signature_bytes': size}


def soft_dependencies(values):
    result = {'pre': [], 'post': []}
    for value in values:
        phase = None
        for token in value.split():
            if token in ('pre:', 'post:'):
                phase = token[:-1]
            elif phase and ':' not in token and '/' not in token:
                result[phase].append(token.replace('-', '_'))
            else:
                raise ValueError('unsupported softdep syntax: ' + value)
    return result


def check_consumer(name, info, imported, providers, tainted):
    failures = []
    for symbol in imported:
        provider = providers.get(symbol)
        if not provider:
            failures.append({'module': name, 'symbol': symbol, 'reason': 'missing provider'})
            continue
        if provider['namespace'] and provider['namespace'] not in info.get('import_ns', []):
            failures.append({'module': name, 'symbol': symbol, 'reason': 'missing namespace',
                             'namespace': provider['namespace']})
        if provider['gpl_only'] and name in tainted:
            failures.append({'module': name, 'symbol': symbol, 'reason': 'GPL-only export to proprietary consumer'})
    return failures


def run(stock, kernel, nm):
    inventory = audit(stock, kernel)
    early = load_names(stock / 'vendor_boot/lib/modules/modules.load')
    selected, ownership, errors = select(inventory['modules'], early)
    if errors or inventory['invalid_modules']:
        raise ValueError('ambiguous or invalid OEM inventory')
    providers, infos, imports, types, reports = {}, {}, {}, {}, {}
    for line in (kernel / 'Module.symvers').read_text().splitlines():
        fields = line.split()
        if fields[2] == 'vmlinux':
            providers[fields[1]] = {'owner': 'vmlinux', 'gpl_only': fields[3] == 'EXPORT_SYMBOL_GPL',
                                    'namespace': fields[4] if len(fields) > 4 else ''}
    for name, row in selected.items():
        path = stock / row['paths'][0]
        info, imported = module_info(path)
        symbols, labels, parts = elf_symbols(path)
        infos[name], imports[name] = info, imported
        types[name] = {s[len('__kcfi_typeid_'):]: v for s, (i, v) in symbols.items()
                       if s.startswith('__kcfi_typeid_')}
        for symbol, policy in export_policy(symbols, labels, parts).items():
            if symbol in providers:
                raise ValueError('duplicate selected export: ' + symbol)
            providers[symbol] = dict(policy, owner=name)
        reports[name] = {'path': row['paths'][0], 'sha256': row['sha256'],
                         'license': info.get('license', []), 'import_ns': info.get('import_ns', []),
                         'softdep': soft_dependencies(info.get('softdep', [])),
                         'signature': signature(path.read_bytes())}
    tainted = {n for n, info in infos.items() if not info.get('license') or
               any(value not in GPL for value in info['license'])}
    # Conservatively propagate proprietary-provider taint independent of symbol order.
    while True:
        extra = {n for n, syms in imports.items() if any(
            providers.get(s, {}).get('owner') in tainted for s in syms)} - tainted
        if not extra:
            break
        tainted |= extra
    failures = []
    for name in selected:
        failures += check_consumer(name, infos[name], imports[name], providers, tainted)
    builtins = {Path(s).stem.replace('-', '_') for s in
                (kernel / 'modules.builtin').read_text().splitlines()}
    soft_missing, early_late = [], []
    for name, row in reports.items():
        for phase, deps in row['softdep'].items():
            for dep in deps:
                if dep not in selected and dep not in builtins:
                    soft_missing.append({'module': name, 'phase': phase, 'dependency': dep})
                elif name in early and dep in selected and not any(
                        p.startswith('vendor_boot/') for p in selected[dep]['paths']):
                    early_late.append({'module': name, 'phase': phase, 'dependency': dep})
    proc = subprocess.run([str(nm), '--defined-only', str(kernel / 'vmlinux')],
                          capture_output=True, text=True, check=True, timeout=120)
    kernel_types = {}
    for line in proc.stdout.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[2].startswith('__kcfi_typeid_'):
            kernel_types[fields[2][len('__kcfi_typeid_'):]] = int(fields[0], 16)
    checked, mismatches, absent = 0, [], 0
    for name, syms in imports.items():
        for symbol in syms:
            provider = providers.get(symbol)
            if not provider:
                continue
            target = kernel_types if provider['owner'] == 'vmlinux' else types[provider['owner']]
            if symbol not in types[name] or symbol not in target:
                absent += 1
                continue
            checked += 1
            if types[name][symbol] != target[symbol]:
                mismatches.append({'module': name, 'symbol': symbol,
                                   'consumer': hex(types[name][symbol]), 'provider': hex(target[symbol])})
    gki = (kernel / 'include/generated/gki_module_unprotected.h').read_text()
    # AOSP Modprobe::InsmodWithDeps ignores failed softdep loads. Keep these
    # OEM baseline gaps visible, but do not pretend they are hard load failures.
    # The OEM loader implementation and actual probe order remain unverified.
    blocked = bool(failures or mismatches)
    entries = re.search(r'gki_unprotected_symbols\[.*?=\s*\{(.*?)\};', gki, re.S)
    if entries is None:
        raise ValueError('unknown GKI allowlist header format')
    return {'schema_version': 1, 'status': 'blocked' if blocked else 'no_detected_loader_metadata_blocker',
            'flash_ready': False, 'selected_names': len(selected),
            'kernel': inventory['kernel'], 'kernel_image_sha256': digest(kernel / 'arch/arm64/boot/Image'),
            'conditional_first_stage_ownership': ownership,
            'namespace_license_failures': failures, 'proprietary_taint_closure': sorted(tainted),
            'softdep_missing': soft_missing, 'early_softdep_later_partition': early_late,
            'signature_status': dict(Counter(r['signature']['status'] for r in reports.values())),
            'kcfi': {'comparable_import_typeids': checked, 'imports_without_comparable_typeids': absent,
                     'mismatches': mismatches, 'scope': 'Available declared import/provider type IDs only, not runtime callbacks'},
            'gki_unprotected_header_sha256': digest(kernel / 'include/generated/gki_module_unprotected.h'),
            'empty_gki_allowlist': not entries.group(1).strip(),
            'softdep_scope': 'Advisory OEM metadata; AOSP softdep loads are non-strict. OEM loader execution unverified.',
            'modules': reports,
            'unverified': ['Signature cryptographic validity/trust; CMS parsing alone is not verification',
                           'Built-in GKI export protection is disabled by the empty generated allowlist',
                           'Softdep loader execution, parameters, init ordering and all driver probes',
                           'Runtime callbacks, indirect-call CFI and structure/layout compatibility',
                           'Bootloader acceptance and live boot/hardware behavior']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stock', type=Path, required=True)
    p.add_argument('--kernel-out', type=Path, required=True)
    p.add_argument('--llvm-nm', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    report = run(a.stock, a.kernel_out, a.llvm_nm)
    a.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('status', 'selected_names', 'signature_status', 'kcfi')}))
    return int(report['status'] == 'blocked')


if __name__ == '__main__':
    raise SystemExit(main())
