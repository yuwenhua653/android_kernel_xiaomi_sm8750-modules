# SPDX-License-Identifier: GPL-2.0-only
"""Read constrained vendor-boot-v4/newc containers without extracting paths."""
import re
import stat
import struct
from pathlib import PurePosixPath


def require(ok, message):
    if not ok:
        raise ValueError(message)


def vendor_v4(data):
    require(len(data) >= 2128 and data[:8] == b'VNDRBOOT', 'not vendor_boot v4')
    version, page = struct.unpack_from('<II', data, 8)
    ramdisk_size, = struct.unpack_from('<I', data, 24)
    header_size, dtb_size = struct.unpack_from('<II', data, 2096)
    table_size, count, entry_size, bootconfig_size = struct.unpack_from('<4I', data, 2112)
    require((version, page, header_size, entry_size) == (4, 4096, 2128, 108), 'unsupported vendor_boot layout')
    require(ramdisk_size > 0 and dtb_size > 0 and count > 0 and table_size == count * entry_size,
            'empty/inconsistent vendor ramdisk table')
    align = lambda value: (value + page - 1) // page * page
    offsets = [align(header_size)]
    for size in (ramdisk_size, dtb_size, table_size):
        offsets.append(offsets[-1] + align(size))
    end = offsets[3] + bootconfig_size
    require(end <= len(data), 'vendor_boot section outside image')
    sections = {'ramdisk': data[offsets[0]:offsets[0] + ramdisk_size],
                'dtb': data[offsets[1]:offsets[1] + dtb_size],
                'bootconfig': data[offsets[3]:end]}
    entries, ranges = [], []
    for i in range(count):
        at = offsets[2] + i * entry_size
        size, offset, kind = struct.unpack_from('<III', data, at)
        name = data[at + 12:at + 44].split(b'\0', 1)[0].decode()
        require(size > 0 and kind in (1, 2, 3) and offset + size <= ramdisk_size,
                'invalid/empty vendor ramdisk entry')
        ranges.append((offset, offset + size))
        entries.append({'size': size, 'offset': offset, 'type': kind, 'name': name,
                        'board_id': list(struct.unpack_from('<16I', data, at + 44))})
    covered = 0
    for begin, end in sorted(ranges):
        require(begin == covered, 'overlapping/gapped ramdisk table')
        covered = end
    require(covered == ramdisk_size, 'ramdisk table does not cover section')
    return sections, {'version': version, 'page_size': page, 'ramdisk_size': ramdisk_size,
                      'dtb_size': dtb_size, 'table_size': table_size, 'entry_size': entry_size,
                      'bootconfig_size': bootconfig_size, 'entries': entries,
                      'cmdline': data[28:2076].split(b'\0', 1)[0].decode()}


def read_newc(data):
    """Return bytes and metadata; never honor archive paths on the filesystem."""
    offset, result = 0, {}
    while offset + 110 <= len(data):
        require(data[offset:offset + 6] == b'070701', 'unsupported/truncated newc header')
        try:
            fields = [int(data[offset + 6 + i * 8:offset + 14 + i * 8], 16) for i in range(13)]
        except ValueError as error:
            raise ValueError('invalid newc hexadecimal field') from error
        inode, mode, uid, gid, nlink, _, size, _, _, _, _, namesize, checksum = fields
        require(namesize > 1 and checksum == 0 and offset + 110 + namesize <= len(data), 'invalid newc name extent')
        rawname = data[offset + 110:offset + 110 + namesize]
        require(rawname[-1:] == b'\0' and b'\0' not in rawname[:-1], 'invalid newc name termination')
        name = rawname[:-1].decode()
        start = (offset + 110 + namesize + 3) & ~3
        require(start + size <= len(data), 'newc data outside archive')
        offset = (start + size + 3) & ~3
        if name == 'TRAILER!!!':
            require(size == 0 and not any(data[offset:]), 'payload after newc trailer')
            return result
        path = PurePosixPath(name)
        require(not path.is_absolute() and '..' not in path.parts and str(path) == name and name != '.',
                'unsafe/noncanonical newc path')
        require(name not in result, 'duplicate newc path')
        require(stat.S_ISDIR(mode) or stat.S_ISREG(mode), 'unexpected nonregular ramdisk member')
        require(nlink == 1 or stat.S_ISDIR(mode), 'unsupported hardlinked ramdisk file')
        if stat.S_ISDIR(mode):
            require(size == 0, 'directory carries data')
        result[name] = {'data': data[start:start + size], 'mode': mode, 'uid': uid, 'gid': gid}
    raise ValueError('missing newc trailer')


def serial_bootconfig(raw, cmdline=''):
    require('androidboot.load_modules_parallel' not in cmdline, 'conflicting command-line parallel setting')
    text = raw.decode()
    lines, found, keys = [], False, set()
    for line in text.splitlines():
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)=(.*)', line)
        require(match is not None, 'requires reviewed flat bootconfig')
        key, value = match.groups()
        require(key not in keys, 'duplicate bootconfig key')
        keys.add(key)
        if key == 'androidboot.load_modules_parallel':
            require(value in ('true', 'false', 'performance', 'conservative'), 'unknown parallel load mode')
            line = key + '=false'
            found = True
        lines.append(line)
    require(found, 'reviewed parallel load setting is missing')
    return ('\n'.join(lines) + '\n').encode()
