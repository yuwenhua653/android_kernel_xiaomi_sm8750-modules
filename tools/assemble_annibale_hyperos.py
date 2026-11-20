#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline R49 OS4.0.6 candidate: stock filesystem plus three network modules.

Does not access devices. Test-key signatures are not Xiaomi signatures; unlocked
bootloader acceptance and hardware operation require separate device testing.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import uuid

from annibale_ramdisk import require
from build_annibale_native_images import verify_stage
from check_annibale_erofs import inspect
from prepare_annibale_boot_candidate import assemble
from stage_annibale_android import check_stripped
from verify_annibale_modules import module_info
from audit_annibale_normal_boot import run as normal_audit
from audit_annibale_loader import run as loader_audit

NAMES = ('rmnet_offload', 'rmnet_core', 'rmnet_shs')
IMAGE_SHA = '96c5ffded4f70f00e80b28bf1daca9484293e2953cb8cc8301350a1e89857d8f'
STOCK_MODULES_SHA = 'e7514100dde41191754e7c6385bfa87b75b42d0a9a22d5b4c7d16f31461374d7'
STOCK = {
    'boot': '37484274a4c91b2fec88e1ae4e9483631c6e96207eac6761a17aaeb6cbf1c47e',
    'vendor_dlkm': '2f156bb8b714b142c6751149655bd3de90842c388b9e4d931696964f2752c6a7',
    'vbmeta': '1632dd1a9ba05bd2ff22315dc9d62f3bc0e83d1b5e82a8415e7c2f65972d8a6c',
}


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def filemap(root):
    result = {}
    for p in root.rglob('*'):
        require(not p.is_symlink(), 'unreviewed symlink: ' + str(p))
        if p.is_file():
            result['/' + p.relative_to(root).as_posix()] = sha(p)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('stock-images', 'stock-modules', 'stage', 'kernel-out', 'external-modules',
                 'avbtool', 'mkfs-erofs', 'fsck-erofs', 'fec', 'test-key', 'nm', 'output'):
        ap.add_argument('--' + name, type=Path, required=True)
    a = ap.parse_args()
    for name, value in vars(a).items():
        setattr(a, name, value.resolve())
    out = a.output
    require(not out.exists(), 'output already exists; refusing to overwrite')
    require(stat.S_IMODE(a.test_key.stat().st_mode) & 0o077 == 0, 'test private key must be private')
    for name, expected in STOCK.items():
        require(sha(a.stock_images / (name + '.img')) == expected, 'wrong stock ' + name)
    inventory_bytes = json.dumps(filemap(a.stock_modules), sort_keys=True, separators=(',', ':')).encode()
    require(hashlib.sha256(inventory_bytes).hexdigest() == STOCK_MODULES_SHA,
            'extracted stock files differ from the reviewed OS4 inventory')
    staged = verify_stage(a.stage)
    require(staged['release'] == '6.6.144-4k-gc17ffa89f4fe', 'wrong staged release')
    for path, expected in staged['kernel_input_sha256'].items():
        require(sha(a.kernel_out / path) == expected, 'kernel/stage mismatch: ' + path)
    out.mkdir(parents=True)
    images = out / 'candidate'; images.mkdir()
    rollback = out / 'stock-rollback'; rollback.mkdir()
    reports = out / 'reports'; reports.mkdir()
    work = out / 'work'; work.mkdir()
    def write(name, value):
        (reports / name).write_text(json.dumps(value, indent=2) + '\n')
    def run(cmd, log):
        env = dict(os.environ, PATH=str(a.fec.parent) + os.pathsep + os.environ['PATH'])
        with (reports / log).open('w') as f:
            subprocess.run(list(map(str, cmd)), stdout=f, stderr=subprocess.STDOUT, env=env, check=True)
    mixed = work / 'modules'
    shutil.copytree(a.stock_modules, mixed)
    baseline = filemap(mixed / 'vendor_dlkm')
    contract = []
    records = {m['name']: m for m in staged['modules']}
    for name in NAMES:
        rel = Path('vendor_dlkm/lib/modules') / (name + '.ko')
        source = list(a.external_modules.rglob(name + '.ko'))
        require(len(source) == 1, 'ambiguous source module ' + name)
        src = source[0]; dst = a.stage / rel
        require(records[name]['source_sha256'] == sha(src) and records[name]['installed_sha256'] == sha(dst), 'stage source mismatch')
        check_stripped(src, dst)
        original_info, original_imports = module_info(mixed / rel)
        new_info, new_imports = module_info(dst)
        # These indexes can remain byte-identical only if dependency, alias and
        # softdep input metadata have not changed. CRC changes are audited below.
        require(set(','.join(original_info.get('depends', [])).split(',')) ==
                set(','.join(new_info.get('depends', [])).split(',')), name + ' changed dependency set')
        for field in ('name', 'alias', 'softdep', 'parm', 'parmtype'):
            require(sorted(original_info.get(field, [])) == sorted(new_info.get(field, [])), name + ' changed ' + field)
        contract.append({'name': name, 'original_sha256': sha(mixed / rel),
                         'source_sha256': sha(src), 'installed_sha256': sha(dst),
                         'imports_added': sorted(new_imports.keys() - original_imports.keys()),
                         'imports_removed': sorted(original_imports.keys() - new_imports.keys()),
                         'indexes_and_parameters_unchanged': True})
        shutil.copyfile(dst, mixed / rel)
    write('module-contract.json', contract)
    abi = normal_audit(mixed, a.kernel_out); write('normal-abi.json', abi)
    require(abi['status'] == 'conditional_abi_pass', 'normal ABI blockers')
    loader = loader_audit(mixed, a.kernel_out, a.nm); write('loader.json', loader)
    require(loader['status'] == 'no_detected_loader_metadata_blocker', 'loader blockers')
    stock_bytes = (a.stock_images / 'vendor_dlkm.img').read_bytes()
    fs_size = struct.unpack_from('<I', stock_bytes, 1060)[0] * 4096
    metadata = inspect(stock_bytes[:fs_size], None, shared_xattrs=True)
    require(set(metadata) == {'/'} | {'/' + p.relative_to(mixed / 'vendor_dlkm').as_posix() for p in (mixed / 'vendor_dlkm').rglob('*')}, 'original metadata and extracted paths differ')
    contexts = work / 'file_contexts'
    contexts.write_text(''.join(re.escape(p) + ' ' + r['selinux'] + '\n' for p, r in sorted(metadata.items())))
    for p, record in metadata.items():
        (mixed / 'vendor_dlkm' / p.lstrip('/')).chmod(stat.S_IMODE(record['mode']))
    fs_image = images / 'vendor_dlkm.img'
    run([a.mkfs_erofs, '-b4096', '-zlz4hc,level=9', '-x999999', '--all-root',
         '-T' + str(struct.unpack_from('<Q', stock_bytes, 1048)[0]),
         '-U' + str(uuid.UUID(bytes=stock_bytes[1072:1088])),
         '--file-contexts=' + str(contexts), fs_image, mixed / 'vendor_dlkm'], 'mkfs-erofs.log')
    new_meta = inspect(fs_image.read_bytes(), None)
    require(set(new_meta) == set(metadata), 'new EROFS paths differ')
    for p in metadata:
        for k in ('mode', 'uid', 'gid', 'selinux'):
            require(new_meta[p][k] == metadata[p][k], 'changed EROFS ' + k + ': ' + p)
    write('erofs-metadata.json', new_meta)
    extracted = work / 'roundtrip'
    run([a.fsck_erofs, '--extract=' + str(extracted), fs_image], 'fsck-erofs.log')
    require(filemap(extracted) == filemap(mixed / 'vendor_dlkm'), 'EROFS data roundtrip failed')
    finalfiles = filemap(extracted)
    changed = sorted(p for p in baseline if baseline[p] != finalfiles[p])
    require(changed == sorted('/lib/modules/' + n + '.ko' for n in NAMES), 'unexpected changed stock files')
    write('erofs-roundtrip.json', {'files': len(finalfiles), 'inodes': len(metadata),
          'changed_files': changed, 'filesystem_bytes': fs_image.stat().st_size,
          'all_other_file_bytes_and_all_labels_modes_owners_preserved': True})
    kernel = (a.kernel_out / 'arch/arm64/boot/Image').read_bytes()
    boot, boot_report = assemble((a.stock_images / 'boot.img').read_bytes(), kernel, kernel_sha=IMAGE_SHA)
    (out / 'boot-UNQUALIFIED.img').write_bytes(boot)
    # assemble's scope is a temporary boot with stock DLKM, not this full candidate.
    write('temporary-boot.json', boot_report)
    (images / 'boot.img').write_bytes(boot)
    sys.path.insert(0, str(a.avbtool.parent))
    import avbtool as avb
    av = avb.Avb()
    def parse(p):
        return av._parse_image(avb.ImageHandler(str(p), read_only=True))
    def props(ds):
        result = []
        for d in ds:
            if isinstance(d, avb.AvbPropertyDescriptor):
                result += ['--prop', d.key + ':' + d.value.decode()]
        return result
    _, bh, bd, _ = parse(a.stock_images / 'boot.img')
    _, vh, vd, _ = parse(a.stock_images / 'vendor_dlkm.img')
    _, th, td, _ = parse(a.stock_images / 'vbmeta.img')
    require(bh.algorithm_type == th.algorithm_type == 2 and vh.algorithm_type == 0 and
            bh.flags == vh.flags == th.flags == 0 and all(h.public_key_metadata_size == 0 for h in (bh, vh, th)), 'unreviewed AVB policy')
    bdesc = [d for d in bd if isinstance(d, avb.AvbHashDescriptor)]
    vdesc = [d for d in vd if isinstance(d, avb.AvbHashtreeDescriptor)]
    require(len(bdesc) == len(vdesc) == 1, 'unexpected footer descriptors')
    bdesc, vdesc = bdesc[0], vdesc[0]
    require(vdesc.fec_num_roots == 2 and vdesc.data_block_size == vdesc.hash_block_size == 4096, 'unreviewed FEC policy')
    common = [sys.executable, a.avbtool]
    run(common + ['add_hash_footer', '--image', images / 'boot.img', '--partition_name', 'boot',
         '--partition_size', str((a.stock_images / 'boot.img').stat().st_size), '--algorithm', 'SHA256_RSA4096',
         '--key', a.test_key, '--salt', bdesc.salt.hex(), '--hash_algorithm', bdesc.hash_algorithm,
         '--rollback_index', str(bh.rollback_index), '--rollback_index_location', str(bh.rollback_index_location)] + props(bd), 'boot-avb.log')
    run(common + ['add_hashtree_footer', '--image', fs_image, '--partition_name', 'vendor_dlkm',
         '--partition_size', str(len(stock_bytes)), '--algorithm', 'NONE', '--salt', vdesc.salt.hex(),
         '--hash_algorithm', vdesc.hash_algorithm, '--block_size', '4096', '--fec_num_roots', '2'] + props(vd), 'dlkm-avb.log')
    run(common + ['extract_public_key', '--key', a.test_key, '--output', out / 'test-key.avbpubkey'], 'public-key.log')
    _, _, new_vd, _ = parse(fs_image)
    new_tree = next(d for d in new_vd if isinstance(d, avb.AvbHashtreeDescriptor))
    new_td = copy.deepcopy(td); changes = []
    for i, d in enumerate(new_td):
        if isinstance(d, avb.AvbChainPartitionDescriptor) and d.partition_name == 'boot':
            d.public_key = (out / 'test-key.avbpubkey').read_bytes(); changes.append(i)
        elif isinstance(d, avb.AvbHashtreeDescriptor) and d.partition_name == 'vendor_dlkm':
            require(d.encode() == vdesc.encode(), 'original parent/child DLKM descriptors differ')
            new_td[i] = new_tree; changes.append(i)
    require(len(changes) == 2, 'expected exactly boot chain and vendor_dlkm descriptor')
    blob = av._generate_vbmeta_blob(
        algorithm_name='SHA256_RSA4096', key_path=str(a.test_key), public_key_metadata_path=None,
        descriptors=new_td, chain_partitions_use_ab=[], chain_partitions_do_not_use_ab=[],
        rollback_index=th.rollback_index, flags=0, rollback_index_location=th.rollback_index_location,
        props=[], props_from_file=[], kernel_cmdlines=[], setup_rootfs_from_kernel=None,
        ht_desc_to_setup=None, include_descriptors_from_image=[], signing_helper=None,
        signing_helper_with_files=None, release_string=th.release_string,
        append_to_release_string=None, required_libavb_version_minor=th.required_libavb_version_minor)
    limit = (a.stock_images / 'vbmeta.img').stat().st_size
    require(len(blob) <= limit, 'vbmeta exceeds original size')
    (images / 'vbmeta.img').write_bytes(blob + bytes(limit - len(blob)))
    _, nh, nd, _ = parse(images / 'vbmeta.img')
    require(avb.verify_vbmeta_signature(nh, blob), 'new vbmeta signature invalid')
    require(len(nd) == len(td), 'descriptor count changed')
    for i in range(len(td)):
        require(nd[i].encode() == new_td[i].encode(), 'descriptor roundtrip failed')
        if i not in changes:
            require(nd[i].encode() == td[i].encode(), 'unmodified AVB descriptor changed')
    for name in ('boot', 'vendor_dlkm'):
        cmd = common + ['verify_image', '--image', images / (name + '.img')]
        if name == 'boot': cmd += ['--key', a.test_key]
        run(cmd, name + '-avb-verify.log')
    # Verify signing key binding and footer metadata, not merely RSA self-consistency.
    foot, nb, nbds, _ = parse(images / 'boot.img')
    data = (images / 'boot.img').read_bytes()[foot.vbmeta_offset:foot.vbmeta_offset + foot.vbmeta_size]
    po = 256 + nb.authentication_data_block_size + nb.public_key_offset
    require(data[po:po + nb.public_key_size] == (out / 'test-key.avbpubkey').read_bytes(), 'boot signing key differs from parent')
    require(nb.rollback_index == bh.rollback_index and nb.flags == bh.flags == 0, 'boot rollback/flags changed')
    require([d.encode() for d in nbds if isinstance(d, avb.AvbPropertyDescriptor)] == [d.encode() for d in bd if isinstance(d, avb.AvbPropertyDescriptor)], 'boot properties changed')
    require(new_tree.fec_num_roots == 2 and new_tree.flags == vdesc.flags and new_tree.salt == vdesc.salt, 'DLKM policy changed')
    fec_input = work / 'fec-input.bin'
    final_dlkm = fs_image.read_bytes()
    fec_input.write_bytes(final_dlkm[:new_tree.fec_offset])
    fec_output = work / 'fec-recomputed.bin'
    run([a.fec, '--encode', '--roots', '2', fec_input, fec_output], 'fec-verify.log')
    require(fec_output.read_bytes()[:new_tree.fec_size] ==
            final_dlkm[new_tree.fec_offset:new_tree.fec_offset + new_tree.fec_size], 'FEC recomputation differs')
    avb_report = {'status': 'offline_verified_test_key_only', 'boot_rollback_index': nb.rollback_index,
                  'top_flags': nh.flags, 'boot_flags': nb.flags, 'fec_roots': new_tree.fec_num_roots,
                  'top_descriptor_count': len(td), 'preserved_descriptor_count': len(td) - len(changes),
                  'changed_descriptors': ['boot chain public key', 'vendor_dlkm hashtree'],
                  'fec_recomputed_and_matched': True,
                  'unchanged_large_partitions_rehashed': False,
                  'test_public_key_sha256': sha(out / 'test-key.avbpubkey'),
                  'bootloader_acceptance': 'UNTESTED: requires unlocked device; never relock'}
    write('avb.json', avb_report)
    for name in STOCK:
        p = images / (name + '.img')
        require(p.stat().st_size == (a.stock_images / p.name).stat().st_size, 'partition size changed')
        shutil.copyfile(a.stock_images / p.name, rollback / p.name)
    write('assembly.json', {'status': 'offline_candidate_built_runtime_unverified', 'device': 'annibale',
          'firmware': 'OS4.0.6.0.XPKCNXM', 'release': staged['release'], 'kernel_sha256': IMAGE_SHA,
          'replacement_modules': list(NAMES), 'partitions': list(STOCK),
          'partition_resize': False, 'verity_disabled': False,
          'runtime_tested': False, 'full_oss_hardware_stack': False})
    print(json.dumps({'output': str(out), 'status': 'offline_candidate_built_runtime_unverified'}))


if __name__ == '__main__':
    main()
