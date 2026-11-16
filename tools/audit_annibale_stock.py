#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Inventory stock-module ABI blockers without modifying modules or the kernel.

Models retaining stock module providers. No result proves HyperOS compatibility,
signature trust, CFI, load order, HALs or bootability. Release strings alone do
not block versioned modules: see kernel/module/version.c:same_magic.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import struct
from verify_annibale_modules import module_info, read_symvers, sections


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exports(path):
    """Read actual __crc_* exports, never guess them from consumer imports."""
    parts = sections(path)
    raw = path.read_bytes()
    head = struct.unpack_from('<16sHHIQQQIHHHHHH', raw)
    headers = [struct.unpack_from('<IIQQQQIIQQ', raw, head[6] + i * 64)
               for i in range(head[12])]
    names = raw[headers[head[13]][4]:headers[head[13]][4] + headers[head[13]][5]]

    def cstring(data, offset):
        end = data.find(b'\0', offset)
        if offset < 0 or end < 0:
            raise ValueError(f'{path}: invalid symbol string')
        return data[offset:end].decode('ascii')

    names = [cstring(names, h[0]) for h in headers]
    crcs, exported, found = {}, set(), False
    for h in headers:
        if h[1] != 2:
            continue
        found = True
        if h[9] != 24 or h[5] % 24 or h[6] >= len(headers):
            raise ValueError(f'{path}: invalid symbol table')
        strings = parts[names[h[6]]]
        for pos in range(h[4], h[4] + h[5], 24):
            name, _, _, index, value, _ = struct.unpack_from('<IBBHQQ', raw, pos)
            name = cstring(strings, name)
            if name.startswith('__ksymtab_'):
                exported.add(name[len('__ksymtab_'):])
            if not name.startswith('__crc_'):
                continue
            symbol = name[len('__crc_'):]
            if index == 0xfff1:
                crc = value
            else:
                if index >= len(headers) or not names[index].startswith('__kcrctab'):
                    raise ValueError(f'{path}: unexpected CRC section for {symbol}')
                section = parts[names[index]]
                if value + 4 > len(section):
                    raise ValueError(f'{path}: truncated CRC for {symbol}')
                crc, = struct.unpack_from('<I', section, value)
            if crc > 0xffffffff or symbol in crcs:
                raise ValueError(f'{path}: invalid/duplicate export CRC for {symbol}')
            crcs[symbol] = crc
    if not found or exported != crcs.keys():
        raise ValueError(f'{path}: missing symbol table/export CRC metadata')
    return crcs


def magic_flags(vermagic):
    release, separator, flags = vermagic.partition(' ')
    if not release or not separator or not flags:
        raise ValueError('invalid vermagic')
    return flags


def compare(imports, stock_exports, kernel_symbols):
    mismatch, missing, stock_mismatch = {}, [], {}
    checked = retained = 0
    for symbol, crc in imports.items():
        target = kernel_symbols.get(symbol)
        if target and target[1] == 'vmlinux':
            checked += 1
            if crc != target[0]:
                mismatch[symbol] = {'stock': f'{crc:08x}', 'kernel': f'{target[0]:08x}'}
        elif symbol in stock_exports:
            available = {entry[1] for entry in stock_exports[symbol]}
            if crc not in available:
                stock_mismatch[symbol] = {'required': f'{crc:08x}',
                                          'available': sorted(f'{v:08x}' for v in available)}
            else:
                retained += 1
        else:
            missing.append(symbol)
    return {'kernel_imports_checked': checked, 'retained_provider_imports': retained,
            'kernel_crc_mismatches': mismatch, 'missing_symbols': sorted(missing),
            'stock_provider_crc_mismatches': stock_mismatch}


def audit(stock_root, kernel_out):
    stock_root, kernel_out = stock_root.resolve(), kernel_out.resolve()
    config = (kernel_out / '.config').read_text().splitlines()
    if 'CONFIG_MODVERSIONS=y' not in config:
        raise ValueError('target must enable CONFIG_MODVERSIONS')
    symbols = read_symvers([kernel_out / 'Module.symvers'])
    if 'module_layout' not in symbols or symbols['module_layout'][1] != 'vmlinux':
        raise ValueError('target lacks the real built-in module_layout export')
    order = (kernel_out / 'modules.order').read_text().splitlines()
    if not order:
        raise ValueError('target needs a linked module to establish vermagic')
    first = Path(order[0]).with_suffix('.ko')
    first = first if first.is_absolute() else kernel_out / first
    if not first.resolve().is_relative_to(kernel_out):
        raise ValueError('target modules.order escapes kernel output')
    target_info, target_imports = module_info(first)
    if target_imports['module_layout'] != symbols['module_layout'][0]:
        raise ValueError('stale target module_layout CRC')
    target_magic = target_info['vermagic'][0]
    release = (kernel_out / 'include/config/kernel.release').read_text().strip()
    if target_magic.split()[0] != release:
        raise ValueError('stale target module release')
    records, errors = {}, []
    files = sorted(stock_root.rglob('*.ko'))
    if not files:
        raise ValueError('stock module inventory is empty')
    for path in files:
        if not path.resolve().is_relative_to(stock_root):
            raise ValueError(f'stock module escapes inventory: {path}')
        relative, key = str(path.relative_to(stock_root)), digest(path)
        if key in records:
            records[key]['paths'].append(relative)
            continue
        try:
            info, imports = module_info(path)
            provided = exports(path)
            records[key] = {'name': info['name'][0].replace('-', '_'), 'paths': [relative],
                            'sha256': key, 'vermagic': info['vermagic'][0],
                            'depends': [n.replace('-', '_') for n in info['depends'][0].split(',') if n],
                            'signed_trailer_present': path.read_bytes().endswith(b'~Module signature appended~\n'),
                            '_imports': imports, '_exports': provided}
        except (ValueError, UnicodeError, struct.error) as error:
            errors.append({'path': relative, 'error': str(error)})
    stock_exports, by_name = defaultdict(list), defaultdict(list)
    for key, record in records.items():
        by_name[record['name']].append(key)
        for symbol, crc in record['_exports'].items():
            stock_exports[symbol].append((record['name'], crc))
    counts, mismatched_symbols = Counter(), Counter()
    for record in records.values():
        record.update(compare(record.pop('_imports'), stock_exports, symbols))
        record['duplicate_builtin_exports'] = sorted(s for s in record.pop('_exports')
            if s in symbols and symbols[s][1] == 'vmlinux')
        record['vermagic_flags_match'] = magic_flags(record['vermagic']) == magic_flags(target_magic)
        record['missing_dependencies'] = sorted(set(record['depends']) - by_name.keys())
        blockers = [k for k in ('kernel_crc_mismatches', 'missing_symbols',
                    'stock_provider_crc_mismatches', 'duplicate_builtin_exports',
                    'missing_dependencies') if record[k]]
        if not record['vermagic_flags_match']:
            blockers.append('vermagic_flags')
        record['blockers'] = blockers
        counts.update(blockers)
        counts['modules_with_detected_blockers'] += bool(blockers)
        mismatched_symbols.update(record['kernel_crc_mismatches'].keys())
    variants = {name: keys for name, keys in by_name.items() if len(keys) > 1}
    load_lists = []
    for path in sorted(stock_root.rglob('modules.load*')):
        if not path.resolve().is_relative_to(stock_root):
            raise ValueError('load list escapes inventory')
        entries = [l.split('#', 1)[0].strip() for l in path.read_text().splitlines()]
        entries = [l for l in entries if l]
        missing = [l for l in entries if Path(l).stem.replace('-', '_') not in by_name]
        load_lists.append({'path': str(path.relative_to(stock_root)), 'entries': len(entries),
                           'missing_from_inventory': missing, 'sha256': digest(path)})
    status = 'blocked' if errors or counts['modules_with_detected_blockers'] else 'no_detected_abi_blocker'
    if status != 'blocked' and (variants or any(x['missing_from_inventory'] for x in load_lists)):
        status = 'incomplete_inventory'
    return {'schema_version': 1, 'status': status,
            'scope': 'All supplied modules, retaining stock providers; not a selected boot load set',
            'kernel': {'release': release, 'vermagic': target_magic,
                       'config_sha256': digest(kernel_out / '.config'),
                       'symvers_sha256': digest(kernel_out / 'Module.symvers')},
            'file_count': len(files), 'unique_binaries': len(records),
            'unique_names': len(by_name), 'counts': dict(counts),
            'top_kernel_crc_mismatches': mismatched_symbols.most_common(25),
            'ambiguous_module_variants': variants, 'load_lists': load_lists,
            'invalid_modules': errors, 'modules': list(records.values()),
            'unverified': ['signature trust (trailer detection is not verification)',
                           'CFI/BTF validation and runtime layout beyond CRCs',
                           'namespace/license restrictions and selected module load order',
                           'duplicate providers across mutually exclusive inventory variants',
                           'boot images, DTB/DTBO, firmware, HALs and hardware behavior']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock-modules', type=Path, required=True)
    parser.add_argument('--kernel-out', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit(args.stock_modules, args.kernel_out)
    except (OSError, ValueError, UnicodeError, struct.error) as error:
        parser.exit(1, f'FAIL: {error}\n')
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(f'{report["status"]}: {report["unique_binaries"]} distinct stock binaries; '
          f'{report["counts"].get("modules_with_detected_blockers", 0)} with detected blockers')
    return 0 if report['status'] == 'no_detected_abi_blocker' else 1


if __name__ == '__main__':
    raise SystemExit(main())
