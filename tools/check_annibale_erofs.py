# SPDX-License-Identifier: GPL-2.0-only
"""Inspect metadata/SELinux labels in locally generated EROFS images.

Constrained to 4 KiB, flat directories, inline xattrs and LZ4 zero padding.
fsck.erofs independently checks and extracts compressed file data.
Format reference: matching kernel fs/erofs/erofs_fs.h.
"""
import stat
import struct
from annibale_ramdisk import require


def inspect(data, label):
    data = bytes(data)
    require(len(data) >= 1152, 'truncated EROFS header')
    def get(fmt, at):
        require(at >= 0 and at + struct.calcsize(fmt) <= len(data), 'EROFS extent outside image')
        return struct.unpack_from(fmt, data, at)
    require(get('<I', 1024)[0] == 0xe0f5e1e2, 'wrong EROFS magic')
    require(data[1036] == 12 and data[1037] == 0, 'unsupported EROFS block/header size')
    require(get('<I', 1104)[0] == 1, 'unexpected EROFS incompatible features')
    root = get('<H', 1038)[0]
    blocks, meta = get('<II', 1060)
    require(blocks * 4096 == len(data), 'EROFS length differs from block count')
    seen, result = set(), {}

    def visit(nid, path):
        require(nid not in seen, 'duplicate/cyclic EROFS inode')
        seen.add(nid)
        at = meta * 4096 + nid * 32
        fmt, count, mode = get('<HHH', at)
        require(fmt & ~15 == 0, 'unsupported inode format')
        extended, layout = fmt & 1, (fmt >> 1) & 7
        ilen = 64 if extended else 32
        size = get('<Q' if extended else '<I', at + 8)[0]
        uid, gid = get('<II' if extended else '<HH', at + 24)
        xlen = 12 + (count - 1) * 4 if count else 0
        require(xlen >= 12 and at + ilen + xlen <= len(data), 'missing/truncated inline xattrs')
        xat, end = at + ilen, at + ilen + xlen
        require(data[xat + 4] == 0, 'shared xattrs are outside this qualification profile')
        xat += 12
        attrs = {}
        while xat < end:
            nlen, index, vlen = get('<BBH', xat)
            require(nlen > 0 and xat + 4 + nlen + vlen <= end, 'invalid inline xattr entry')
            name = data[xat + 4:xat + 4 + nlen]
            key = (index, name)
            require(key not in attrs, 'duplicate xattr')
            attrs[key] = data[xat + 4 + nlen:xat + 4 + nlen + vlen]
            xat += (4 + nlen + vlen + 3) & ~3
        context = attrs.get((6, b'selinux'), b'').removesuffix(b'\0')
        require(context == label.encode(), 'wrong/missing SELinux label: ' + path)
        require(uid == gid == 0, 'non-root image owner')
        directory = stat.S_ISDIR(mode)
        require(directory or stat.S_ISREG(mode), 'unexpected EROFS member type')
        require(stat.S_IMODE(mode) == (0o755 if directory else 0o644), 'wrong image mode')
        result[path] = {'mode': mode, 'uid': uid, 'gid': gid, 'size': size, 'selinux': context.decode()}
        if not directory:
            return
        require(layout in (0, 2), 'unsupported directory data layout')
        raw = get('<I', at + 16)[0] * 4096
        chunks = []
        for offset in range(0, size, 4096):
            length = min(4096, size - offset)
            start = at + ilen + xlen if layout == 2 and length < 4096 else raw + offset
            require(start + length <= len(data), 'directory block outside image')
            chunks.append(data[start:start + length])
        names = set()
        for block in chunks:
            require(len(block) >= 12, 'short directory block')
            first, = struct.unpack_from('<H', block, 8)
            require(first % 12 == 0 and 12 <= first <= len(block), 'invalid directory name offset')
            for off in range(0, first, 12):
                child, begin, _, _ = struct.unpack_from('<QHBB', block, off)
                finish = struct.unpack_from('<H', block, off + 20)[0] if off + 12 < first else len(block)
                require(first <= begin < finish <= len(block), 'invalid directory name span')
                name = block[begin:finish].split(b'\0', 1)[0].decode()
                if name in ('.', '..'):
                    continue
                require(name and '/' not in name and name not in names, 'unsafe/duplicate directory name')
                names.add(name)
                visit(child, (path.rstrip('/') + '/' + name))
    visit(root, '/')
    return result
