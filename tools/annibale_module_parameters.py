#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read Linux 6.6 ARM64 kernel_param records, including module_param_cb.

.modinfo parmtype alone omits callback parameters. This checks ELF relocations
and reports real sysfs permissions; it does not validate parameter values.
"""
import struct
from verify_annibale_modules import sections


def module_parameters(path):
    parts = sections(path)  # Validate architecture, section bounds and names.
    if not parts.get('__param'):
        return {}
    data = path.read_bytes()
    hdr = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
    headers = [struct.unpack_from('<IIQQQQIIQQ', data, hdr[6] + 64*i)
               for i in range(hdr[12])]
    names_h = headers[hdr[13]]
    names = data[names_h[4]:names_h[4]+names_h[5]]
    def name(h):
        return names[h[0]:names.index(b'\0', h[0])].decode('ascii')
    idx = next(i for i, h in enumerate(headers) if name(h) == '__param')
    table = parts['__param']
    def require(ok, message):
        if not ok:
            raise ValueError(f'{path}: {message}')
    require(len(table) % 40 == 0, 'invalid ARM64 kernel_param size')
    relocs = [h for h in headers if h[7] == idx and h[1] in (4, 9)]
    require(len(relocs) == 1, 'missing/ambiguous parameter relocations')
    rel = relocs[0]
    require(rel[1] == 4 and rel[9] == 24 and rel[5] % 24 == 0,
            'invalid parameter RELA table')
    require(0 < rel[6] < len(headers), 'invalid relocation symbol table')
    sym = headers[rel[6]]
    require(sym[1] == 2 and sym[9] == 24 and sym[5] % 24 == 0,
            'invalid parameter symbol table')
    resolved = {}
    for pos in range(rel[4], rel[4]+rel[5], 24):
        offset, info, addend = struct.unpack_from('<QQq', data, pos)
        require(offset+8 <= len(table), 'parameter relocation outside table')
        if offset % 40:
            continue  # ops, module and argument pointers are not name strings.
        require(info & 0xffffffff == 257, 'parameter name needs R_AARCH64_ABS64')
        symbol_index = info >> 32
        require(symbol_index < sym[5]//24, 'invalid parameter symbol index')
        _, _, _, section_index, value, _ = struct.unpack_from('<IBBHQQ', data, sym[4]+symbol_index*24)
        require(0 < section_index < len(headers), 'undefined parameter name')
        target = headers[section_index]
        start = value + addend
        require(target[1] != 8 and 0 <= start < target[5], 'parameter name outside section')
        blob = data[target[4]:target[4]+target[5]]
        end = blob.find(b'\0', start)
        require(end > start, 'empty/unterminated parameter name')
        param = blob[start:end].decode('ascii')
        require(all(c.isalnum() or c in '_-.' for c in param), 'invalid parameter name')
        require(offset not in resolved, 'duplicate parameter name relocation')
        resolved[offset] = param
    require(set(resolved) == set(range(0, len(table), 40)), 'missing parameter name relocation')
    result = {}
    for offset, param in sorted(resolved.items()):
        require(param not in result, 'duplicate parameter name')
        permission = struct.unpack_from('<H', table, offset+24)[0]
        require(permission & ~0o777 == 0, 'invalid parameter permission')
        result[param] = {'permission': permission, 'source': '__param'}
    return result
