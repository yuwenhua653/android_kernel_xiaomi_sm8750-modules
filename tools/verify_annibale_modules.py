#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check linked ARM64 modules against this build's real symbol providers.

This verifies same-build symbol CRCs/dependencies, not Android KMI allowlists,
stock-module compatibility, trusted signatures, driver probe or hardware.
"""
import argparse
from graphlib import CycleError, TopologicalSorter
import hashlib
import json
from pathlib import Path
import struct


def sections(path):
    data = path.read_bytes()
    if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01':
        raise ValueError(f'{path}: expected little-endian ELF64')
    header = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
    if header[1] != 1 or header[2] != 183:
        raise ValueError(f'{path}: expected ARM64 relocatable module')
    offset, size, count, names_index = header[6], header[11], header[12], header[13]
    if size != 64 or not count or names_index >= count or offset + size * count > len(data):
        raise ValueError(f'{path}: invalid section table')
    headers = [struct.unpack_from('<IIQQQQIIQQ', data, offset + i * size)
               for i in range(count)]

    def contents(h):
        if h[1] == 8:  # SHT_NOBITS has no bytes in the file.
            return b''
        if h[4] + h[5] > len(data):
            raise ValueError(f'{path}: section exceeds file')
        return data[h[4]:h[4] + h[5]]

    names = contents(headers[names_index])
    result = {}
    for h in headers:
        if h[0] >= len(names) or names.find(b'\0', h[0]) < 0:
            raise ValueError(f'{path}: invalid section name')
        name = names[h[0]:names.index(b'\0', h[0])].decode('ascii')
        if name:
            if name in result:
                raise ValueError(f'{path}: duplicate section {name}')
            result[name] = contents(h)
    return result


def module_info(path):
    parts = sections(path)
    info = {}
    for item in parts.get('.modinfo', b'').split(b'\0'):
        if b'=' in item:
            key, value = item.decode().split('=', 1)
            info.setdefault(key, []).append(value)
    for key in ('name', 'vermagic', 'depends'):
        if len(info.get(key, [])) != 1:
            raise ValueError(f'{path}: missing/ambiguous {key}')
    versions = parts.get('__versions', b'')
    if not versions or len(versions) % 64:
        raise ValueError(f'{path}: missing/invalid modversion records')
    imports = {}
    for pos in range(0, len(versions), 64):
        crc, name = struct.unpack_from('<Q56s', versions, pos)
        if b'\0' not in name:
            raise ValueError(f'{path}: unterminated modversion name')
        name = name.split(b'\0', 1)[0].decode('ascii')
        if not name or name in imports:
            raise ValueError(f'{path}: empty/duplicate modversion name')
        imports[name] = crc
    if 'module_layout' not in imports:
        raise ValueError(f'{path}: module_layout version absent')
    return info, imports


def read_symvers(paths):
    symbols = {}
    for path in paths:
        for line in path.read_text().splitlines():
            fields = line.split()
            if len(fields) < 4:
                raise ValueError(f'{path}: malformed symvers line')
            crc, name, provider = int(fields[0], 16), fields[1], fields[2]
            if name in symbols and symbols[name] != (crc, provider):
                raise ValueError(f'duplicate symbol provider: {name}')
            symbols[name] = (crc, provider)
    return symbols


def verify(kernel_out, module_stage):
    config = (kernel_out / '.config').read_text().splitlines()
    if 'CONFIG_MODVERSIONS=y' not in config:
        raise ValueError('this verifier requires CONFIG_MODVERSIONS=y')
    release = (kernel_out / 'include/config/kernel.release').read_text().strip()
    symbols = read_symvers([kernel_out / 'Module.symvers', module_stage / 'Module.symvers'])
    # modules.order is authoritative: do not pick up obsolete .ko files in caches.
    paths = []
    for root in (kernel_out, module_stage):
        order = (root / 'modules.order').read_text().splitlines()
        if not order:
            raise ValueError(f'{root}: empty modules.order')
        for entry in order:
            p = Path(entry)
            p = p if p.is_absolute() else root / p
            p = p.with_suffix('.ko').resolve()
            if not p.is_relative_to(root.resolve()) or not p.is_file():
                raise ValueError(f'ordered module missing/outside build: {p}')
            if p in paths:
                raise ValueError(f'duplicate module in modules.order: {p}')
            paths.append(p)
    modules = {}
    vermagics = set()
    for p in paths:
        info, imports = module_info(p)
        if 'CONFIG_DEBUG_INFO_BTF_MODULES=y' in config and not sections(p).get('.BTF'):
            raise ValueError(f'{p}: required module BTF is missing')
        # Linux module-name matching treats '-' and '_' as equivalent.
        name, vermagic = info['name'][0].replace('-', '_'), info['vermagic'][0]
        if name in modules:
            raise ValueError(f'duplicate module name: {name}')
        if vermagic.split()[0] != release:
            raise ValueError(f'{name}: wrong release {vermagic}')
        vermagics.add(vermagic)
        for symbol, crc in imports.items():
            if symbol not in symbols or symbols[symbol][0] != crc:
                raise ValueError(f'{name}: missing or mismatched CRC for {symbol}')
        with p.open('rb') as f:
            digest = hashlib.file_digest(f, 'sha256').hexdigest()
        modules[name] = {'path': str(p), 'sha256': digest, 'versioned_imports': len(imports),
                         'depends': [n.replace('-', '_') for n in info['depends'][0].split(',') if n]}
    if len(vermagics) != 1:
        raise ValueError('modules disagree on vermagic flags')
    for name, module in modules.items():
        missing = set(module['depends']) - modules.keys()
        if missing:
            raise ValueError(f'{name}: unresolved module dependencies {sorted(missing)}')
    try:
        dependency_order = list(TopologicalSorter(
            {name: tuple(module['depends']) for name, module in modules.items()}
        ).static_order())
    except CycleError as error:
        raise ValueError('cyclic module dependencies: ' + ' -> '.join(error.args[1])) from error
    return {'release': release, 'vermagic': next(iter(vermagics)),
            'kernel_module_count': sum(p.is_relative_to(kernel_out.resolve()) for p in paths),
            'external_module_count': sum(p.is_relative_to(module_stage.resolve()) for p in paths),
            'modules': modules,
            'dependency_order': dependency_order,
            'dependency_order_scope': 'Hard dependencies only; not a device modules.load list, softdep policy or probe ordering',
            'scope': 'same-build ARM64 ELF, modversions, vermagic and acyclic hard dependency graph only'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-out', type=Path, required=True)
    parser.add_argument('--module-stage', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify(args.kernel_out.resolve(), args.module_stage.resolve())
    except (ValueError, OSError, UnicodeError, struct.error) as error:
        parser.exit(1, f'FAIL: {error}\n')
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(f'PASS: {report["kernel_module_count"]} kernel and '
          f'{report["external_module_count"]} external modules; '
          'ARM64, symbol CRCs, vermagic and dependencies')


if __name__ == '__main__':
    main()
