#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Stage Android text depmod indexes and native loaders for a partial source plan.

This is not a ROM installer or boot image builder. Never modifies source modules,
stock firmware, or an existing output directory. No proprietary assets are copied.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile

from audit_annibale_stock import exports
from check_annibale_audio_assets import check as check_assets
from check_annibale_rom_paths import check_build_inputs, digest
from plan_annibale_modules import PARTITIONS, module_name, resolve
from verify_annibale_modules import module_info, sections, verify

MOUNTS = {'vendor_boot': '', 'system_dlkm': 'system', 'vendor_dlkm': 'vendor'}


def runtime_path(entry):
    mount = MOUNTS[entry['partition']]
    return '/' + (mount + '/' if mount else '') + 'lib/modules/' + Path(entry['source']).name


def loader(mode, release, boot_modules=()):
    if mode not in ('system', 'vendor') or not re.fullmatch(r'[A-Za-z0-9_.+-]+', release):
        raise ValueError('invalid loader mode or kernel release')
    template = Path(__file__).with_name('annibale_native_loader.sh.in').read_text()
    checks = []
    for name in boot_modules:
        if module_name(name) != name:
            raise ValueError('noncanonical vendor_boot module name')
        checks.append(f'[ -d /sys/module/{name} ] || fail "vendor_boot prerequisite absent: {name}"')
    return template.replace('@MODE@', mode).replace('@RELEASE@', release).replace('@BOOT_CHECKS@', '\n'.join(checks))


def check_stripped(source, destination):
    if module_info(source) != module_info(destination):
        raise ValueError(f'modinfo/import CRC changed after strip: {source.name}')
    if exports(source) != exports(destination):
        raise ValueError(f'export CRC changed after strip: {source.name}')
    before, after = sections(source), sections(destination)
    for section in ('.BTF', '.BTF.ext'):
        if before.get(section) != after.get(section):
            raise ValueError(f'{section} changed after strip: {source.name}')
    return {s: len(before[s]) for s in ('.BTF', '.BTF.ext') if s in before}


def validate_dep(text, entries, verification):
    """All generated references must be installed; check actual ELF hard deps too."""
    paths = {runtime_path(e): e['name'] for e in entries}
    names = {v: k for k, v in paths.items()}
    if len(names) != len(entries):
        raise ValueError('duplicate module path/name in depmod input')
    parsed = {}
    for line in text.splitlines():
        if line.count(':') != 1:
            raise ValueError('malformed modules.dep line')
        name, deps = line.split(':')
        dep_list = deps.split()
        if name not in paths or name in parsed or any(d not in paths for d in dep_list):
            raise ValueError('unknown/duplicate runtime path in modules.dep')
        if name in dep_list or len(set(dep_list)) != len(dep_list):
            raise ValueError('self/duplicate dependency in modules.dep')
        parsed[name] = dep_list
    if set(parsed) != set(paths):
        raise ValueError('depmod omitted a staged module')
    for path, name in paths.items():
        for dep in verification['modules'][name]['depends']:
            dep = module_name(dep)
            if dep in names and names[dep] not in parsed[path]:
                raise ValueError(f'depmod omitted hard dependency: {name} -> {dep}')
    return {'module_records': len(parsed), 'dependency_references': sum(map(len, parsed.values()))}


def write_make_example(output, plan):
    lines = [
        '# REVIEW ONLY: partial normal-boot audio/network qualification, not a full BoardConfig.',
        '# Copy/review into the device tree only after completing hardware coverage and init policy.',
        '# Set ANNIBALE_MODULE_STAGE to the generated directory, relative to the Android tree.',
        'ifeq ($(strip $(ANNIBALE_MODULE_STAGE)),)',
        '$(error ANNIBALE_MODULE_STAGE must name the qualified module stage)', 'endif',
        '# Replace existing stock/prebuilt module owners; never append these lists.',
    ]
    for partition, prefix in (('vendor_boot', 'VENDOR_RAMDISK'),
                              ('system_dlkm', 'SYSTEM'), ('vendor_dlkm', 'VENDOR')):
        variable = f'BOARD_{prefix}_KERNEL_MODULES'
        lines += [f'ifneq ($(strip $({variable}) $({variable}_LOAD)),)',
                  f'$(error Existing {prefix} module owner must be reviewed and removed)', 'endif']
        paths = [f'$(ANNIBALE_MODULE_STAGE)/{e["destination"]}' for e in plan['entries']
                 if e['partition'] == partition]
        continuation = ' ' + chr(92) + '\n    '
        lines += [variable + ' :=' + continuation + continuation.join(paths), f'{variable}_LOAD := $({variable})']
    lines += ['# Modules were already stripped and checked by this staging tool.',
              'BOARD_DO_NOT_STRIP_VENDOR_RAMDISK_MODULES := true',
              'BOARD_DO_NOT_STRIP_VENDOR_MODULES := true',
              '# Android build regenerates indexes from these inputs; compare final image contents.',
              '# Review system_dlkm/vendor_dlkm image flags, fstab, AVB and size limits separately.',
              '# Do not apply this file to HyperOS or recovery.']
    (output / 'BoardConfig.modules.mk.example').write_text('\n'.join(lines) + '\n')
    product = [
        '# REVIEW ONLY: replace existing copy owners; reuse existing gki/vendor.modprobe services.',
        '# Also review Soong prebuilt owners and vendor SELinux labels before enabling.',
        'ifeq ($(strip $(ANNIBALE_MODULE_STAGE)),)',
        '$(error ANNIBALE_MODULE_STAGE must name the qualified module stage)', 'endif',
    ]
    for filename in ('system_dlkm_modprobe.sh', 'vendor_modprobe.sh'):
        destination = '$(TARGET_COPY_OUT_VENDOR)/bin/' + filename
        product += [f'ifneq ($(filter %:{destination},$(PRODUCT_COPY_FILES)),)',
                    f'$(error Existing copy owner for {filename} must be removed)', 'endif',
                    f'PRODUCT_COPY_FILES += $(ANNIBALE_MODULE_STAGE)/native-loader/{filename}:{destination}']
    (output / 'Product.modules-loader.mk.example').write_text('\n'.join(product) + '\n')


def stage(kout, external, policy_path, output, depmod, strip, odm_root=None):
    inputs = check_build_inputs(kout, external)
    builtin = kout / 'modules.builtin'
    build = json.loads((external / 'build.json').read_text())
    if build['kernel_inputs'].get(str(builtin)) != digest(builtin):
        raise ValueError('stale/unrecorded modules.builtin')
    verification = verify(kout, external)
    policy = json.loads(policy_path.read_text())
    plan = resolve(verification, policy,
                   {module_name(Path(n).stem) for n in builtin.read_text().splitlines()})
    if plan.get('audio_variant') not in ('tfa', 'sia'):
        raise ValueError('explicit audio family required')
    if output.exists() or output.is_symlink():
        raise ValueError('output must not exist')
    output = output.resolve()
    protected = (kout, external, Path(__file__).resolve().parents[1])
    if any(output == p or p in output.parents or output in p.parents for p in protected):
        raise ValueError('output overlaps source/build trees')
    report = {'schema_version': 1, 'status': 'android_stage_passed', 'flashable': False,
              'complete_device': False, 'audio_variant': plan['audio_variant'],
              'release': plan['release'], 'kernel_input_sha256': inputs,
              'policy_sha256': digest(policy_path), 'tools': {
                  'depmod_sha256': digest(depmod), 'strip_sha256': digest(strip),
                  'strip_executable_name': strip.name,
                  'stager_sha256': digest(Path(__file__)),
                  'loader_template_sha256': digest(Path(__file__).with_name('annibale_native_loader.sh.in'))},
              'modules': [], 'partitions': {},
              'unverified': ['Full device driver coverage and final Android images',
                             'Actual init/SELinux/mount execution and module signatures',
                             'Hardware probe, HAL/firmware behavior and audio routing']}
    if odm_root:
        asset_manifest = Path(__file__).resolve().parents[1] / 'Documentation/xiaomi/annibale-os4-audio-assets.json'
        report['audio_assets'] = check_assets(odm_root, json.loads(asset_manifest.read_text()), plan['audio_variant'])
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=output.name + '-', dir=output.parent))
    try:
        for entry in plan['entries']:
            source, dest = Path(entry['source']), temp / entry['destination']
            if digest(source) != entry['sha256']:
                raise ValueError('module changed since verification')
            dest.parent.mkdir(parents=True, exist_ok=True)
            stripped = entry['partition'] != 'system_dlkm'
            if stripped:
                if source.read_bytes().endswith(b'~Module signature appended~\n'):
                    raise ValueError(f'refusing to strip signed module: {source}')
                subprocess.run([str(strip), '--strip-debug', '-o', str(dest), str(source)], check=True)
            else:
                shutil.copyfile(source, dest)
            btf = check_stripped(source, dest)
            if module_info(dest)[0].get('name') != [module_name(dest.stem)]:
                raise ValueError('loader basename does not match the actual kernel module name')
            report['modules'].append({'name': entry['name'], 'destination': entry['destination'],
                                      'source_sha256': entry['sha256'], 'installed_sha256': digest(dest),
                                      'stripped': stripped, 'source_size': source.stat().st_size,
                                      'installed_size': dest.stat().st_size, 'btf_sections': btf})
        for partition in PARTITIONS:
            own = [e for e in plan['entries'] if e['partition'] == partition]
            extra = [e for e in plan['entries'] if e['partition'] == 'system_dlkm'] if partition == 'vendor_dlkm' else []
            with tempfile.TemporaryDirectory(prefix='annibale-depmod-', dir=output.parent) as depdir:
                root = Path(depdir) / 'lib/modules/0.0'
                root.mkdir(parents=True)
                for e in own + extra:
                    target = root / runtime_path(e).lstrip('/')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(temp / e['destination'], target)
                # Use the real built-in list rather than inventing providers to silence depmod.
                shutil.copyfile(builtin, root / 'modules.builtin')
                if (kout / 'modules.builtin.modinfo').exists():
                    shutil.copyfile(kout / 'modules.builtin.modinfo', root / 'modules.builtin.modinfo')
                (root / 'modules.order').write_text(''.join(runtime_path(e).lstrip('/') + '\n' for e in own + extra))
                config = Path(depdir) / 'empty-depmod.conf'
                config.write_text('')
                run = subprocess.run([str(depmod), '-C', str(config), '-b', depdir, '0.0'],
                                     check=True, text=True, capture_output=True)
                if run.stderr.strip():
                    raise ValueError('depmod diagnostics: ' + run.stderr)
                dep = (root / 'modules.dep').read_text()
                dep = re.sub(r'([^:\s]*lib/modules/[^:\s]+)', r'/\1', dep)
                # Apply the Android absolute-path rewrite to each line, never across newlines.
                checked = validate_dep(dep, own + extra, verification)
                target = temp / partition / 'lib/modules'
                (target / 'modules.dep').write_text(dep)
                for name in ('modules.alias', 'modules.softdep'):
                    shutil.copyfile(root / name, target / name)
                (target / 'modules.load').write_text(''.join(Path(e['source']).name + '\n' for e in own))
                checked['installed_module_count'] = len(own)
                checked['runtime_directory'] = '/' + (MOUNTS[partition] + '/' if MOUNTS[partition] else '') + 'lib/modules'
                report['partitions'][partition] = checked
        scripts = temp / 'native-loader'
        scripts.mkdir()
        for mode, name in (('system', 'system_dlkm_modprobe.sh'), ('vendor', 'vendor_modprobe.sh')):
            path = scripts / name
            path.write_text(loader(mode, plan['release'], plan['partitions']['vendor_boot']))
            path.chmod(0o755)
        write_make_example(temp, plan)
        (temp / 'README.txt').write_text(
            'PARTIAL NATIVE SOURCE QUALIFICATION; NOT FLASHABLE.\n'
            'Audio and network subset only; retain no stock modules in these lists.\n'
            'Do not overwrite a ROM, HyperOS, recovery, or a device partition with this stage.\n'
            'Review Documentation/xiaomi/annibale-android-staging.md before device integration.\n'
            'No proprietary firmware/config/calibration is included; asset checks are metadata only.\n')
        report['selected_module_count'] = len(plan['entries'])
        report['preloaded_vendor_boot_dependencies'] = [e for e in plan['ordering_edges']
            if e['before'] in plan['partitions']['vendor_boot'] and e['after'] not in plan['partitions']['vendor_boot']]
        (temp / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
        manifest = {str(p.relative_to(temp)): {'size': p.stat().st_size, 'sha256': digest(p)}
                    for p in sorted(temp.rglob('*')) if p.is_file()}
        (temp / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        temp.rename(output)
        return report
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('kernel-out', 'module-stage', 'policy', 'output', 'depmod', 'strip'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--odm-root', type=Path)
    args = parser.parse_args()
    try:
        result = stage(args.kernel_out.resolve(), args.module_stage.resolve(), args.policy.resolve(),
                       args.output.absolute(), args.depmod.absolute(), args.strip.absolute(), args.odm_root)
    except (OSError, ValueError, KeyError, TypeError, struct.error, subprocess.CalledProcessError) as error:
        parser.exit(1, f'FAIL: {error}\n')
    print(f'PASS: {result["selected_module_count"]} staged modules; Android text indexes and strip invariants; NOT boot-qualified')


if __name__ == '__main__':
    main()
