#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build the Annibale touch/media/NFC/DSP group with one strict modpost.

Copies source into a fresh staging tree. No installation or flashing. This is
link qualification of the LOS media baseline plus Annibale touch/PHY changes,
not a claim of complete Xiaomi display, audio or camera support.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from verify_annibale_modules import verify


GROUPS = (
    'qcom/opensource/mm-drivers/msm_ext_display',
    'qcom/opensource/mm-drivers/hw_fence',
    'qcom/opensource/mm-drivers/sync_fence',
    'qcom/opensource/mmrm-driver',
    'qcom/opensource/synx-kernel',
    'qcom/opensource/securemsm-kernel',
    'qcom/opensource/display-drivers',
    'qcom/opensource/audio-kernel',
    'qcom/opensource/camera-kernel',
    'qcom/opensource/dsp-kernel',
    'nxp/opensource/driver',
    'xiaomi/touch/annibale',
)


def sha256(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def build_options(kernel, stage):
    qcom = stage / 'qcom/opensource'
    mm = qcom / 'mm-drivers'
    return [
        f'KERNEL_SRC={kernel}', f'KERNEL_ROOT={kernel}',
        f'DISPLAY_ROOT={qcom / "display-drivers"}',
        f'AUDIO_ROOT={qcom / "audio-kernel"}',
        f'CAMERA_KERNEL_ROOT={qcom / "camera-kernel"}',
        f'SSG_MODULE_ROOT={qcom / "securemsm-kernel"}',
        f'MMRM_ROOT={qcom / "mmrm-driver"}',
        f'SYNX_ROOT={qcom / "synx-kernel"}',
        f'DSP_ROOT={qcom / "dsp-kernel"}',
        f'NFC_ROOT={stage / "nxp/opensource/driver"}',
        f'MSM_EXT_DISPLAY_ROOT={mm}',
        f'MSM_HW_FENCE_ROOT={mm}/', f'SYNC_FENCE_ROOT={mm}/',
        'MODNAME=annibale', 'CONFIG_DRM_MSM=m',
        'CONFIG_TOUCHSCREEN_XIAOMI_ANNIBALE=m',
        'CONFIG_DISABLE_TEST_MODULES=y',
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--kernel-out', type=Path, required=True)
    parser.add_argument('--clang-bin', type=Path, required=True)
    parser.add_argument('--kernel-tools-bin', type=Path,
                        help='AOSP kernel-build-tools/linux-x86/bin (pahole and adjacent libelf)')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--jobs', type=int, choices=range(1, 10), default=3)
    parser.add_argument('--objects', action='store_true',
                        help='compile directories only; no modpost or loadable modules')
    parser.add_argument('--resume-stage', type=Path,
                        help='reuse a stage only if all source hashes still match')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    kernel, kout, clang, output = (p.resolve() for p in
                                  (args.kernel, args.kernel_out, args.clang_bin, args.output))
    for tree in (repo, kernel, kout):
        if output == tree or tree in output.parents:
            parser.error('--output must be outside source and kernel-output trees')
    required = [kernel / 'Makefile', kout / '.config',
                kout / 'include/generated/autoconf.h',
                kout / 'include/config/kernel.release', clang / 'clang']
    if not args.objects:
        required += [kout / 'Module.symvers', kout / 'vmlinux',
                     kout / 'arch/arm64/boot/Image', kout / 'modules.order']
    for path in required:
        if not path.is_file() or path.stat().st_size == 0:
            parser.error(f'missing/non-complete kernel input: {path}')
    config = (kout / '.config').read_text()
    for option in ['CONFIG_ARCH_SUN=y', 'CONFIG_MODULES=y',
                   'CONFIG_QCOM_PANEL_EVENT_NOTIFIER=m']:
        if option not in config.splitlines():
            parser.error(f'required kernel option missing: {option}')
    if not args.objects and not (kout / 'Module.symvers').read_text().strip():
        parser.error('kernel Module.symvers must not be empty')
    env = dict(os.environ, PATH=f'{clang}:{os.environ.get("PATH", "")}')
    host_options = []
    if args.kernel_tools_bin:
        kernel_tools = args.kernel_tools_bin.resolve()
        root = kernel_tools.parent
        for path in (kernel_tools / 'pahole', root / 'include/libelf.h', root / 'lib64/libelf.so'):
            if not path.is_file():
                parser.error(f'missing kernel build tool input: {path}')
        env['PATH'] = f'{kernel_tools}:{env["PATH"]}'
        host_options = [f'HOSTCFLAGS={env.get("HOSTCFLAGS", "")} -I{root}/include',
                        f'HOSTLDFLAGS={env.get("HOSTLDFLAGS", "")} -L{root}/lib64 -Wl,-rpath,{root}/lib64']
    if 'CONFIG_DEBUG_INFO_BTF_MODULES=y' in config.splitlines() and not shutil.which('pahole', path=env['PATH']):
        parser.error('BTF modules require pahole; supply --kernel-tools-bin or install host pahole')
    for key in ('KBUILD_MODPOST_WARN', 'KBUILD_MODPOST_NOFINAL', 'KBUILD_EXTRA_SYMBOLS',
                'KBUILD_MIXED_TREE', 'KBUILD_MODPOST_ALLOW_MISSING_NAMESPACE_IMPORTS'):
        if env.get(key):
            parser.error(f'unset {key}: qualification must use strict complete inputs')
    output.mkdir(parents=True, exist_ok=True)
    kbuild = '# SPDX-License-Identifier: GPL-2.0-only\n' + ''.join(f'obj-m += {g}/\n' for g in GROUPS)
    copy_groups = (*GROUPS, 'qcom/opensource/mm-drivers/config')
    sources = {str(p.relative_to(repo)): sha256(p) for group in copy_groups
               for p in sorted((repo / group).rglob('*')) if p.is_file()}
    sources['Kbuild'] = hashlib.sha256(kbuild.encode()).hexdigest()
    if args.resume_stage:
        stage = args.resume_stage.resolve()
        if stage.parent != output:
            parser.error('--resume-stage must be a direct child of --output')
        previous = json.loads((stage / 'build.json').read_text())
        if previous['source_files'] != sources:
            parser.error('source changes require a fresh stage; existing artifacts preserved')
        for path, digest in sources.items():
            staged = stage / path
            if not staged.is_file() or sha256(staged) != digest:
                parser.error(f'staged source differs: {path}; use a fresh stage')
    else:
        stage = Path(tempfile.mkdtemp(prefix='modules-', dir=output))
        for group in copy_groups:
            shutil.copytree(repo / group, stage / group)
        (stage / 'Kbuild').write_text(kbuild)
    command = ['make', '-C', str(kernel), f'O={kout}', f'M={stage}',
               'ARCH=arm64', 'LLVM=1', 'LLVM_IAS=1', 'HOSTCC=gcc', f'-j{args.jobs}']
    command += host_options
    command += build_options(kernel, stage)
    command += ([f'{g}/' for g in GROUPS] if args.objects else ['modules'])
    inputs = {str(p): sha256(p) for p in required if p != clang / 'clang'}
    metadata = {'stage': str(stage), 'command': command, 'kernel_inputs': inputs,
                'objects_only': args.objects,
                'source_commit': subprocess.check_output(
                    ['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip(),
                'source_dirty': bool(subprocess.check_output(
                    ['git', '-C', str(repo), 'status', '--porcelain'], text=True).strip()),
                'source_files': sources}
    (stage / 'build.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print('Staged sources:', stage, flush=True)
    print('Validation:', 'objects only' if args.objects else 'modules with strict modpost', flush=True)
    with (stage / 'build.log').open('w') as log:
        result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
    metadata['returncode'] = result.returncode
    metadata['make_returncode'] = result.returncode
    metadata['verification_status'] = 'not_run'
    metadata['kernel_inputs_unchanged'] = all(sha256(Path(p)) == digest
                                             for p, digest in inputs.items())
    metadata['modules'] = [{ 'path': str(p.relative_to(stage)), 'sha256': sha256(p)}
                           for p in sorted(stage.rglob('*.ko'))]
    (stage / 'build.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print('Build log:', stage / 'build.log', flush=True)
    if result.returncode:
        print((stage / 'build.log').read_text()[-10000:], flush=True)
    if not metadata['kernel_inputs_unchanged']:
        print('FAIL: kernel inputs changed during the build', flush=True)
        metadata['returncode'] = 1
        (stage / 'build.json').write_text(json.dumps(metadata, indent=2) + '\n')
        return 1
    if not result.returncode and not args.objects:
        try:
            report = verify(kout, stage)
            required_names = {'camera', 'msm_drm', 'machine_dlkm', 'nxp_nci',
                              'frpc_adsprpc', 'goodix_core', 'xiaomi_touch',
                              'msm_ext_display', 'msm_hw_fence', 'synx_driver'}
            missing = required_names - report['modules'].keys()
            if missing:
                raise ValueError(f'missing selected modules: {sorted(missing)}')
        except (ValueError, OSError) as error:
            print(f'FAIL: post-link verification: {error}', flush=True)
            metadata.update(returncode=1, verification_status='failed', verification_error=str(error))
            (stage / 'build.json').write_text(json.dumps(metadata, indent=2) + '\n')
            return 1
        (stage / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
        metadata['verification_status'] = 'passed'
        (stage / 'build.json').write_text(json.dumps(metadata, indent=2) + '\n')
        print(f'PASS: {report["external_module_count"]} external modules, '
              'same-build CRCs, ARM64, vermagic and dependency presence', flush=True)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
