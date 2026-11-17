#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Create a partial source-built kernel handoff and a pinned ROM conversion patch.

Does not modify the reference tree, install into a ROM, sign or flash anything.
Kernel compilation remains a separate verified step; this is not a Soong hook.
"""
import argparse
import difflib
import json
from pathlib import Path
import shutil
import subprocess

from annibale_ramdisk import require
from build_annibale_native_images import file_sha, verify_stage
from stage_annibale_android import loader, write_make_example

REFERENCE_COMMIT = '1ed1eccfa3f68e1ec440b7f5e87ac97dc89475fe'
HANDOFF_PATH = 'device/xiaomi/annibale-oss-kernel'
LOADER_RUNTIME_PACKAGES = ('sh_vendor', 'toolbox_vendor', 'toybox_vendor')


def convert(files):
    """Only convert reviewed owners; reject unexpected text rather than fuzzy edits."""
    before = dict(files)
    board = files['BoardConfig.mk']
    start, end = board.index('# Kernel prebuilt\n'), board.index('# Partitions\n')
    require(board.count('androidboot.load_modules_parallel=true') == 1, 'bootconfig owner changed')
    board = board[:start] + '# Source-built kernel handoff (partial normal-boot qualification)\n' + \
        f'include {HANDOFF_PATH}/BoardConfig.mk\n\n' + board[end:]
    board = board.replace('androidboot.load_modules_parallel=true', 'androidboot.load_modules_parallel=false')
    old_policy = 'include device/qcom/sepolicy_vndr/SEPolicy.mk'
    require(board.splitlines().count(old_policy) == 1, 'Qualcomm policy include owner changed')
    # The reviewed CAF branch uses SEPOLICY_PATH=.../sm8750 internally.
    # Include it from the same standard manifest location so qva SPU labels resolve.
    board = board.replace(old_policy, 'include device/qcom/sepolicy_vndr/sm8750/SEPolicy.mk')
    files['BoardConfig.mk'] = board
    old_copy = '$(LOCAL_PATH)/rootdir/etc/fstab.qcom:$(TARGET_COPY_OUT_VENDOR_RAMDISK)/first_stage_ramdisk/fstab.qcom'
    require(files['device.mk'].count(old_copy) == 1, 'first-stage fstab owner changed')
    files['device.mk'] = files['device.mk'].replace(old_copy, old_copy.replace('/rootdir/etc/fstab.qcom:', '/rootdir/etc/fstab.annibale-oss:'))
    files['device.mk'] += f'\n# Source-built module loaders; replaces extracted script owners.\ninclude {HANDOFF_PATH}/Product.mk\n'
    old_src = 'src: "etc/fstab.qcom",'
    require(files['rootdir/Android.bp'].count(old_src) == 1, 'vendor fstab owner changed')
    files['rootdir/Android.bp'] = files['rootdir/Android.bp'].replace(old_src, 'src: "etc/fstab.annibale-oss",')
    proprietary = files['proprietary-files.txt']
    for path in ('vendor/bin/system_dlkm_modprobe.sh', 'vendor/bin/vendor_modprobe.sh'):
        require(proprietary.splitlines().count(path) == 1, 'unexpected proprietary script owner: ' + path)
        proprietary = proprietary.replace(path + '\n', '')
    files['proprietary-files.txt'] = proprietary
    # Keep the existing recovery fstab untouched; this is normal-boot work.
    patch = ''.join(''.join(difflib.unified_diff(before[p].splitlines(True), files[p].splitlines(True),
                    fromfile='a/' + p, tofile='b/' + p)) for p in sorted(files) if files[p] != before[p])
    return files, patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('kernel-out', 'stage', 'native-images', 'rom-reference', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    stage = args.stage.resolve()
    result = verify_stage(stage)
    images = json.loads((args.native_images / 'validation.json').read_text())
    require(images['status'] == 'offline_images_passed' and images['flashable'] is False and images['display_mode'] == 'native' and
            images['stage_validation_sha256'] == file_sha(stage / 'validation.json') and
            images['family'] == result['audio_variant'], 'image/stage mismatch')
    for name in ('.config', 'arch/arm64/boot/Image', 'Module.symvers', 'include/config/kernel.release'):
        require(file_sha(args.kernel_out / name) == result['kernel_input_sha256'][name], 'kernel/stage mismatch')
    for name in ('dtb', 'dtbo'):
        require(file_sha(args.native_images / (name + '.img')) == images['images'][name]['sha256'], 'stale DT')
    reference = args.rom_reference.resolve()
    head = subprocess.check_output(['git', '-C', str(reference), 'rev-parse', 'HEAD'], text=True).strip()
    require(head == REFERENCE_COMMIT, 'unreviewed ROM reference commit')
    require(not subprocess.check_output(['git', '-C', str(reference), 'status', '--porcelain']), 'reference tree must be clean')
    files = {p: (reference / p).read_text() for p in ('BoardConfig.mk', 'device.mk', 'proprietary-files.txt', 'rootdir/Android.bp')}
    converted, patch = convert(files)
    fstab = (repo / 'configs/annibale/native/fstab.qcom').read_text()
    patch += ''.join(difflib.unified_diff([], fstab.splitlines(True),
                     fromfile='/dev/null', tofile='b/rootdir/etc/fstab.annibale-oss'))
    headers = args.kernel_out / 'usr/include'
    header_files = sorted(headers.rglob('*.h'))
    require(len(header_files) > 900 and (headers / 'asm/unistd.h').is_file() and
            (headers / 'linux/version.h').is_file(), 'run the matching ARM64 make headers target first')
    out = args.output.resolve()
    protected = (repo, stage, args.kernel_out.resolve(), reference, args.native_images.resolve())
    require(not out.exists() and not any(p == out or p in out.parents or out in p.parents for p in protected), 'output exists/overlaps inputs')
    out.mkdir(parents=True)
    handoff = out / 'handoff'; handoff.mkdir()
    shutil.copyfile(args.kernel_out / 'arch/arm64/boot/Image', handoff / 'Image')
    dtbs = handoff / 'dtbs'; dtbs.mkdir()
    # One concatenated file preserves R24 order under Android's sorted *.dtb rule.
    shutil.copyfile(args.native_images / 'dtb.img', dtbs / 'annibale.dtb')
    shutil.copyfile(args.native_images / 'dtbo.img', handoff / 'dtbo.img')
    for partition in ('vendor_boot', 'system_dlkm', 'vendor_dlkm'):
        shutil.copytree(stage / partition, handoff / 'modules' / partition)
    entries = [dict(e, partition=e['destination'].split('/')[0]) for e in result['modules']]
    write_make_example(handoff, {'entries': entries})
    (handoff / 'BoardConfig.modules.mk.example').rename(handoff / 'Modules.mk')
    (handoff / 'Product.modules-loader.mk.example').unlink()
    scripts = handoff / 'native-loader'; scripts.mkdir()
    early = [e['name'] for e in entries if e['partition'] == 'vendor_boot']
    for mode, filename in [('system', 'system_dlkm_modprobe.sh'), ('vendor', 'vendor_modprobe.sh')]:
        p = scripts / filename
        p.write_text(loader(mode, result['release'], early)); p.chmod(0o755)
    bp = ['// SPDX-License-Identifier: Apache-2.0', '// Independent source loaders; preserve existing init service and SELinux owners.',
          'soong_namespace {}']
    for filename in ('system_dlkm_modprobe.sh', 'vendor_modprobe.sh'):
        bp += ['sh_binary {', f'    name: "{filename}",', f'    src: "native-loader/{filename}",', '    vendor: true,', '}']
    (handoff / 'Android.bp').write_text('\n'.join(bp) + '\n')
    hroot = handoff / 'kernel-headers/include'
    for p in header_files:
        require(not p.is_symlink(), 'unexpected exported-header symlink')
        dest = hroot / p.relative_to(headers); dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dest)
    (handoff / 'kernel-headers/Makefile').write_text('# SPDX-License-Identifier: GPL-2.0-only\n'
        '# Export-only adapter for the already generated matching UAPI headers.\n'
        'VERSION = 6\nPATCHLEVEL = 6\n.PHONY: headers_install all\n'
        'headers_install:\n\t@test -n "$(O)"\n\t@mkdir -p "$(O)/usr/include"\n'
        '\t@cp -a "$(CURDIR)/include/." "$(O)/usr/include/"\nall:\n\t@true\n')
    (handoff / 'BoardConfig.mk').write_text(f'''# SPDX-License-Identifier: GPL-2.0-only
# Partial normal-boot handoff, not a full device qualification.
ANNIBALE_KERNEL_HANDOFF := {HANDOFF_PATH}
ANNIBALE_MODULE_STAGE := $(ANNIBALE_KERNEL_HANDOFF)/modules
TARGET_NO_KERNEL_OVERRIDE := true
TARGET_KERNEL_SOURCE := $(ANNIBALE_KERNEL_HANDOFF)/kernel-headers
BOARD_PREBUILT_DTBIMAGE_DIR := $(ANNIBALE_KERNEL_HANDOFF)/dtbs
BOARD_PREBUILT_DTBOIMAGE := $(ANNIBALE_KERNEL_HANDOFF)/dtbo.img
PRODUCT_COPY_FILES += $(ANNIBALE_KERNEL_HANDOFF)/Image:kernel
include $(ANNIBALE_KERNEL_HANDOFF)/Modules.mk
# Put the top-level early list into its own nonempty type-3 ramdisk fragment.
BOARD_VENDOR_RAMDISK_FRAGMENTS += dlkm
BOARD_VENDOR_RAMDISK_FRAGMENT.dlkm.KERNEL_MODULE_DIRS := top
BOARD_VENDOR_RAMDISK_FRAGMENT.dlkm.MKBOOTIMG_ARGS := --ramdisk_type DLKM
# init_boot must be generated from the selected native platform's generic ramdisk.
ifneq ($(strip $(BOARD_PREBUILT_INIT_BOOT_IMAGE)),)
$(error Remove the prebuilt init_boot owner before enabling the native handoff)
endif
''')
    (handoff / 'Product.mk').write_text(f'''# SPDX-License-Identifier: GPL-2.0-only
# Do not add a second init service or replace init.qti.kernel.rc here.
PRODUCT_PACKAGES += system_dlkm_modprobe.sh vendor_modprobe.sh {' '.join(LOADER_RUNTIME_PACKAGES)}
PRODUCT_SOONG_NAMESPACES += {HANDOFF_PATH}
PRODUCT_BUILD_INIT_BOOT_IMAGE := true
''')
    (out / 'annibale-rom-conversion.patch').write_text(patch)
    report = {'schema_version': 1, 'status': 'handoff_prepared', 'flashable': False,
              'rom_reference_commit': head, 'family': result['audio_variant'], 'release': result['release'],
              'stage_validation_sha256': file_sha(stage / 'validation.json'),
              'image_validation_sha256': file_sha(args.native_images / 'validation.json'),
              'loader_template_sha256': file_sha(repo / 'tools/annibale_native_loader.sh.in'),
              'module_count': len(entries), 'header_count': len(header_files),
              'kernel_compilation_hook': False, 'rom_built': False, 'init_boot_built': False,
              'unverified': ['Full native Android 17 ROM and proprietary firmware/HAL compatibility',
                             'Re-extracted vendor tree must not retain conflicting loader owners',
                             'Actual init service graph, vendor tools and enforcing policy',
                             'Recovery/charger module lists and physical partition/AVB configuration',
                             'Device driver coverage, amplifier identity and first boot']}
    (out / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    manifest = {str(p.relative_to(out)): {'sha256': file_sha(p), 'size': p.stat().st_size}
                for p in sorted(out.rglob('*')) if p.is_file()}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'PASS: {len(entries)} source modules, {len(header_files)} UAPI headers, pinned ROM patch; no ROM/init_boot build')


if __name__ == '__main__':
    main()
