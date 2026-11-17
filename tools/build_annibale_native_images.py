#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Assemble offline native boot/vendor_boot/DTBO/EROFS candidates.

No device, signing, vbmeta, dynamic-partition resizing or flashing operations.
The qualified source subset is still incomplete for a full native ROM.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import uuid

from annibale_ramdisk import read_newc, require, vendor_v4
from check_annibale_erofs import inspect as inspect_erofs
from prepare_annibale_boot_candidate import assemble, STOCK_SHA
from prepare_annibale_ramdisk_fragment import STOCK_VENDOR_BOOT_SHA


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_stage(stage):
    manifest = json.loads((stage / 'manifest.json').read_text())
    files = set()
    for path in stage.rglob('*'):
        require(not path.is_symlink(), 'symlink in native stage')
        if path.is_file():
            relative = str(path.relative_to(stage))
            if relative == 'manifest.json':
                continue
            files.add(relative)
            require(relative in manifest and file_sha(path) == manifest[relative]['sha256'] and
                    path.stat().st_size == manifest[relative]['size'], 'stale/unrecorded stage file: ' + relative)
    require(files == manifest.keys(), 'missing staged files')
    result = json.loads((stage / 'validation.json').read_text())
    require(result['status'] == 'android_stage_passed' and result['complete_device'] is False,
            'requires partial source-native qualified stage')
    return result


def check_fstab(text):
    rows = [line.split() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    require(all(len(r) == 5 for r in rows), 'malformed fstab row')
    require(not any(r[2] in ('mifs', 'overlay') or 'mi_ext' in ' '.join(r) for r in rows), 'stock-only fstab owner')
    for partition in ('vendor_dlkm', 'system_dlkm'):
        matches = [r for r in rows if r[1] == '/' + partition]
        require(len(matches) == 1 and matches[0][:3] == [partition, '/' + partition, 'erofs'], 'wrong DLKM filesystem')
        require({'wait', 'slotselect', 'logical', 'first_stage_mount', 'avb=vbmeta'} <= set(matches[0][4].split(',')),
                'missing DLKM mount/AVB flags')
    data = [r for r in rows if r[1] == '/data']
    require(len(data) == 1 and data[0][2] == 'f2fs', 'requires reviewed F2FS data candidate')
    flags = data[0][4].split(',')
    require('fileencryption=aes-256-xts:aes-256-cts:v2+inlinecrypt_optimized+wrappedkey_v0' in flags and
            'metadata_encryption=aes-256-xts:wrappedkey_v0' in flags, 'userdata encryption changed')
    require(any(r[1] == '/metadata' and r[2] == 'f2fs' and 'first_stage_mount' in r[4].split(',') for r in rows),
            'missing early metadata mount')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('kernel-out', 'stage', 'fragment', 'dt-images', 'devicetrees', 'stock-boot',
                 'stock-vendor-boot', 'mkbootimg', 'unpack-bootimg', 'mkfs-erofs', 'fsck-erofs',
                 'mkbootfs', 'lz4', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--display-mode', choices=('default', 'native'), required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(args.devicetrees.resolve() / 'tools'))
    from build_annibale_dt_images import parse_bases, parse_table, selection_matrix
    stage = args.stage.resolve()
    staged = verify_stage(stage)
    family = staged['audio_variant']
    require(family in ('tfa', 'sia'), 'unknown amplifier profile')
    fragment = json.loads((args.fragment / 'validation.json').read_text())
    require(fragment['status'] == 'fragment_passed' and fragment['family'] == family and
            fragment['stage_validation_sha256'] == file_sha(stage / 'validation.json'), 'fragment/stage mismatch')
    for filename, key in [('vendor_dlkm_fragment.cpio', 'cpio_sha256'), ('vendor_dlkm_fragment.lz4', 'lz4_sha256'),
                          ('bootconfig-native-candidate.txt', 'bootconfig_sha256')]:
        require(file_sha(args.fragment / filename) == fragment[key], 'fragment changed: ' + filename)
    early = read_newc((args.fragment / 'vendor_dlkm_fragment.cpio').read_bytes())
    for name, entry in early.items():
        if stat.S_ISREG(entry['mode']):
            require(entry['data'] == (stage / 'vendor_boot' / name).read_bytes(), 'early module bytes differ')
    dt_report = json.loads((args.dt_images / 'validation.json').read_text())
    profile = family + '-' + args.display_mode
    dtb, dtbo = (args.dt_images / 'dtb.img').read_bytes(), (args.dt_images / profile / 'dtbo.img').read_bytes()
    require(dt_report['status'] == 'passed' and sha(dtb) == dt_report['dtb_sha256'] and
            sha(dtbo) == dt_report['profiles'][profile]['dtbo_sha256'], 'stale DT container')
    parse_bases(dtb)
    selection_matrix(parse_table(dtbo))
    for name in ('.config', 'arch/arm64/boot/Image', 'Module.symvers', 'include/config/kernel.release'):
        require(file_sha(args.kernel_out / name) == staged['kernel_input_sha256'][name], 'kernel/stage input mismatch')
    config = (args.kernel_out / '.config').read_text().splitlines()
    for key in ('EROFS_FS', 'EROFS_FS_XATTR', 'EROFS_FS_SECURITY', 'EROFS_FS_ZIP', 'LZ4_DECOMPRESS',
                'EXT4_FS', 'F2FS_FS', 'FS_ENCRYPTION', 'DM_DEFAULT_KEY', 'DM_VERITY'):
        require('CONFIG_' + key + '=y' in config, 'missing kernel filesystem/security option: ' + key)
    fstab = repo / 'configs/annibale/native/fstab.qcom'
    rows = check_fstab(fstab.read_text())
    stock_vb = args.stock_vendor_boot.read_bytes()
    require(sha(stock_vb) == STOCK_VENDOR_BOOT_SHA, 'wrong original vendor_boot')
    _, old_layout = vendor_v4(stock_vb)
    # Retain only technical display/filesystem/bootconfig tokens; do not label a native ROM with OEM build fingerprints.
    cmdline = ' '.join(token for token in old_layout['cmdline'].split()
                       if not token.startswith(('swinfo.fingerprint=', 'mtdoops.fingerprint=', 'bootmonitor.fingerprint=')))
    require(cmdline == 'video=vfb:640x400,bpp=32,memsize=3072000 erofs.reserved_pages=64 bootconfig',
            'unreviewed vendor command line')
    out = args.output.resolve()
    require(not out.exists() and all(p.resolve() not in out.parents for p in (args.stage, args.fragment, args.dt_images, args.kernel_out)),
            'output exists/overlaps verified inputs')
    out.mkdir(parents=True)
    logs = out / 'logs'; logs.mkdir()

    def run(cmd, log):
        with (logs / log).open('w') as stream:
            subprocess.run(list(map(str, cmd)), stdout=stream, stderr=subprocess.STDOUT, check=True)

    platform = out / 'platform-ramdisk'
    (platform / 'first_stage_ramdisk').mkdir(parents=True)
    shutil.copyfile(fstab, platform / 'first_stage_ramdisk/fstab.qcom')
    platform_cpio = subprocess.check_output([str(args.mkbootfs), str(platform)])
    members = read_newc(platform_cpio)
    require(set(members) == {'first_stage_ramdisk', 'first_stage_ramdisk/fstab.qcom'} and
            members['first_stage_ramdisk/fstab.qcom']['data'] == fstab.read_bytes(), 'platform archive differs')
    (out / 'platform.cpio').write_bytes(platform_cpio)
    with (out / 'platform.lz4').open('wb') as stream:
        subprocess.run([str(args.lz4), '-l', '-12', '-c', str(out / 'platform.cpio')], stdout=stream, stderr=subprocess.PIPE, check=True)
    bootconfig = (args.fragment / 'bootconfig-native-candidate.txt').read_bytes()
    (out / 'bootconfig').write_bytes(bootconfig)
    (out / 'dtb.img').write_bytes(dtb)
    (out / 'dtbo.img').write_bytes(dtbo)
    run([sys.executable, args.mkbootimg, '--header_version', '4', '--pagesize', '4096', '--base', '0',
         '--kernel_offset', hex(struct.unpack_from('<I', stock_vb, 16)[0]),
         '--ramdisk_offset', hex(struct.unpack_from('<I', stock_vb, 20)[0]),
         '--tags_offset', hex(struct.unpack_from('<I', stock_vb, 2076)[0]),
         '--dtb_offset', hex(struct.unpack_from('<Q', stock_vb, 2104)[0]),
         '--vendor_cmdline', cmdline, '--dtb', out / 'dtb.img', '--vendor_bootconfig', out / 'bootconfig',
         '--vendor_ramdisk', out / 'platform.lz4', '--ramdisk_type', 'dlkm', '--ramdisk_name', 'dlkm',
         '--vendor_ramdisk_fragment', args.fragment / 'vendor_dlkm_fragment.lz4',
         '--vendor_boot', out / 'vendor_boot.img'], 'mkbootimg.log')
    vb = (out / 'vendor_boot.img').read_bytes()
    sections, layout = vendor_v4(vb)
    require(len(vb) < len(stock_vb) and [e['type'] for e in layout['entries']] == [1, 3], 'invalid vendor_boot size/types')
    require(sections['dtb'] == dtb and sections['bootconfig'] == bootconfig, 'vendor_boot DT/config bytes changed')
    for index, expected in enumerate((platform_cpio, (args.fragment / 'vendor_dlkm_fragment.cpio').read_bytes())):
        entry = layout['entries'][index]
        compressed = sections['ramdisk'][entry['offset']:entry['offset'] + entry['size']]
        actual = subprocess.check_output([str(args.lz4), '-d', '-c'], input=compressed)
        require(actual == expected, 'vendor_boot fragment roundtrip mismatch')
    kernel = (args.kernel_out / 'arch/arm64/boot/Image').read_bytes()
    boot, _ = assemble(args.stock_boot.read_bytes(), kernel, stock_sha=STOCK_SHA, kernel_sha=sha(kernel))
    (out / 'boot.img').write_bytes(boot)
    for name in ('boot', 'vendor_boot'):
        run([sys.executable, args.unpack_bootimg, '--boot_img', out / (name + '.img'), '--out', out / ('unpacked-' + name)],
            'unpack-' + name + '.log')
    require((out / 'unpacked-boot/kernel').read_bytes() == kernel, 'AOSP boot unpack differs')
    require((out / 'unpacked-vendor_boot/dtb').read_bytes() == dtb, 'AOSP vendor DT unpack differs')
    require((out / 'unpacked-vendor_boot/bootconfig').read_bytes() == bootconfig, 'AOSP bootconfig unpack differs')
    for index, expected in enumerate((out / 'platform.lz4', args.fragment / 'vendor_dlkm_fragment.lz4')):
        require((out / 'unpacked-vendor_boot' / ('vendor_ramdisk%02d' % index)).read_bytes() == expected.read_bytes(),
                'AOSP vendor fragment unpack differs')
    filesystems = {}
    for partition, context in [('system_dlkm', 'u:object_r:system_dlkm_file:s0'), ('vendor_dlkm', 'u:object_r:vendor_file:s0')]:
        source = stage / partition
        contexts = out / (partition + '.file_contexts')
        contexts.write_text('/' + partition + '(/.*)? ' + context + '\n')
        image = out / (partition + '.img')
        run([args.mkfs_erofs, '-zlz4hc', '-b4096', '-T', '0', '-x999999', '--all-root',
             '-U', str(uuid.uuid5(uuid.NAMESPACE_URL, 'annibale-native-' + partition)),
             '--mount-point=/' + partition, '--file-contexts=' + str(contexts),
             image, source], 'mkfs-' + partition + '.log')
        metadata = inspect_erofs(image.read_bytes(), context)
        destination = out / ('extracted-' + partition)
        run([args.fsck_erofs, '--extract=' + str(destination), '--no-preserve-owner', '--preserve-perms', image],
            'fsck-' + partition + '.log')
        expected = {str(p.relative_to(source)): p for p in source.rglob('*') if p.is_file()}
        actual = {str(p.relative_to(destination)): p for p in destination.rglob('*') if p.is_file()}
        require(actual.keys() == expected.keys(), 'filesystem member set changed')
        require(set(metadata) == {'/'} | {'/' + str(p.relative_to(source)) for p in source.rglob('*')}, 'metadata member set changed')
        for name, path in actual.items():
            require(not path.is_symlink() and path.read_bytes() == expected[name].read_bytes(), 'filesystem bytes changed: ' + name)
        filesystems[partition] = {'sha256': file_sha(image), 'bytes': image.stat().st_size, 'files': len(actual),
                                   'inodes_checked': len(metadata), 'selinux': context, 'file_data_roundtrip': True,
                                   'uid_gid_mode_labels_checked': True, 'incompatible_features': 1}
    result = {'schema_version': 1, 'status': 'offline_images_passed', 'flashable': False, 'boot_verified': False,
              'complete_device': False, 'family': family, 'display_mode': args.display_mode, 'release': staged['release'],
              'kernel_rebuilt': False, 'modules': staged['selected_module_count'], 'fstab_rows': len(rows),
              'fstab_sha256': file_sha(fstab), 'stage_validation_sha256': file_sha(stage / 'validation.json'),
              'fragment_validation_sha256': file_sha(args.fragment / 'validation.json'),
              'dt_validation_sha256': file_sha(args.dt_images / 'validation.json'), 'vendor_boot_layout': layout,
              'images': {n: {'sha256': file_sha(out / (n + '.img')), 'bytes': (out / (n + '.img')).stat().st_size}
                         for n in ('boot', 'vendor_boot', 'dtbo', 'dtb')}, 'filesystems': filesystems,
              'tools_sha256': {n: file_sha(getattr(args, n)) for n in ('mkbootimg', 'unpack_bootimg', 'mkfs_erofs', 'fsck_erofs', 'mkbootfs', 'lz4')},
              'avb_signatures_added': False, 'original_avb_footer_copied': False,
              'unverified': ['Complete native ROM device tree, init_boot, module-loader owners and enforcing SELinux',
                             'Full device module/firmware/HAL coverage and physical amplifier family',
                             'Final AVB/vbmeta, dynamic partition group sizes, recovery and bootloader behavior',
                             'Actual storage mounts, encrypted data unlock and first OSS boot',
                             'GKI policy and runtime signatures/CFI; experimental empty unprotected list']}
    (out / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    (out / 'README.txt').write_text('OFFLINE PARTIAL NATIVE IMAGES; NOT FLASHABLE.\n'
                                  'No init_boot, recovery, vbmeta, signing or resizing/flash instructions are supplied.\n'
                                  'Do not combine with original HyperOS vendor modules/services.\n'
                                  'Full ROM ownership, module coverage, firmware and hardware remain unqualified.\n')
    print('PASS: boot + two-fragment vendor_boot + selected DTBO + labeled EROFS DLKM; NOT boot-qualified')


if __name__ == '__main__':
    main()
