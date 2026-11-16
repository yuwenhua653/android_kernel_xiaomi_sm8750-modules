#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Make an UNQUALIFIED unsigned boot-v4 candidate for the pinned OS4 baseline.

Only replace boot's kernel. Never transplant the OEM AVB signature or modify
init_boot/vendor_boot/dtbo/DLKM. No device access or flashing is implemented.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

STOCK_SHA = '37484274a4c91b2fec88e1ae4e9483631c6e96207eac6761a17aaeb6cbf1c47e'
KERNEL_SHA = '9cbcb7a3e7fbd65cc6e13424ec8dd089fc6d0e09ead56201868b612c1432d503'
PAGE = 4096


def sha(data):
    return hashlib.sha256(data).hexdigest()


def assemble(stock, kernel, stock_sha=STOCK_SHA, kernel_sha=KERNEL_SHA):
    if sha(stock) != stock_sha or sha(kernel) != kernel_sha:
        raise ValueError('input SHA256 does not match the reviewed baseline')
    if len(stock) < PAGE or stock[:8] != b'ANDROID!':
        raise ValueError('not an Android boot image')
    old_size, ramdisk, _, header_size = struct.unpack_from('<4I', stock, 8)
    version, = struct.unpack_from('<I', stock, 40)
    signature_size, = struct.unpack_from('<I', stock, 1580)
    if (version, header_size, ramdisk, signature_size) != (4, 1584, 0, 0):
        raise ValueError('requires kernel-only v4 boot without boot_signature')
    if stock[24:40] != bytes(16) or any(stock[1584:PAGE]):
        raise ValueError('unexpected reserved header bytes')
    if len(kernel) < 64 or kernel[56:60] != b'ARMd':
        raise ValueError('requires uncompressed ARM64 Image')
    magic, major, minor, original, vbmeta_offset, vbmeta_size = struct.unpack_from(
        '>4sIIQQQ', stock, len(stock) - 64)
    if (magic != b'AVBf' or major != 1 or minor != 0 or
            original < PAGE + old_size or vbmeta_offset < original or
            vbmeta_offset + vbmeta_size > len(stock) - 64):
        raise ValueError('invalid original AVB footer/layout')
    header = bytearray(stock[:PAGE])
    struct.pack_into('<I', header, 8, len(kernel))
    result = bytes(header) + kernel + bytes((-len(kernel)) % PAGE)
    if len(result) >= len(stock):
        raise ValueError('candidate exceeds original partition size')
    return result, {'schema_version': 1, 'status': 'offline_unqualified',
                    'flash_ready': False, 'stock_boot_sha256': sha(stock),
                    'kernel_sha256': sha(kernel), 'candidate_sha256': sha(result),
                    'candidate_bytes': len(result), 'partition_bytes': len(stock),
                    'header_version': 4, 'ramdisk_size': 0, 'boot_signature_size': 0,
                    'avb_footer_present': False,
                    'preserve_stock': ['init_boot', 'vendor_boot', 'dtbo', 'recovery',
                                       'vendor_dlkm', 'system_dlkm', 'vbmeta', 'vbmeta_system'],
                    'unverified': ['Bootloader accepts unsigned candidate',
                                   'Live device/build and rollback policy',
                                   'Modules/signature/CFI/runtime ABI',
                                   'Actual userdata filesystem',
                                   'Recoverable installation method'],
                    'scope': 'Tests the kernel baseline with retained OEM drivers; does not test source display/touch modules'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock-boot', type=Path, required=True)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    image, report = assemble(args.stock_boot.read_bytes(), args.kernel.read_bytes())
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'boot-UNQUALIFIED.img').write_bytes(image)
    (args.output / 'candidate.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    raise SystemExit(main())
