#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check/stage an explicit native source partition plan, not a boot installer.

Resolve hard dependencies, ELF softdeps and reviewed board dependencies. Never
infer partition ownership from a source directory or silently use stock modules.
The produced candidate lists still need Android loader and device validation.
"""
import argparse
from graphlib import CycleError, TopologicalSorter
import json
from pathlib import Path
import re
import shutil
import struct
import tempfile

from check_annibale_rom_paths import check_build_inputs, digest
from verify_annibale_modules import verify

PARTITIONS = ('vendor_boot', 'system_dlkm', 'vendor_dlkm')


def module_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_-]*', value):
        raise ValueError(f'invalid module name: {value!r}')
    return value.replace('-', '_')


def softdeps(lines):
    result = {'pre': [], 'post': []}
    for line in lines:
        mode = None
        count = 0
        for word in line.split():
            if word in ('pre:', 'post:'):
                if mode is not None and count == 0:
                    raise ValueError(f'empty softdep clause: {line}')
                mode, count = word[:-1], 0
            else:
                if mode is None:
                    raise ValueError(f'missing softdep direction: {line}')
                result[mode].append(module_name(word))
                count += 1
        if mode is None or count == 0:
            raise ValueError(f'empty softdep clause: {line}')
    return result


def resolve(verification, policy, builtins):
    if (policy.get('schema_version') != 1
            or policy.get('profile') != 'native-source-qualification'
            or policy.get('boot_mode') != 'normal'
            or policy.get('complete_device') is not False):
        raise ValueError('expected normal native-source qualification policy, not a stock/recovery/install profile')
    modules = verification['modules']
    if set(modules) & builtins:
        raise ValueError('module and builtin names overlap')
    roots = [module_name(n) for n in policy['roots']]
    if not roots or len(set(roots)) != len(roots):
        raise ValueError('empty/duplicate roots')
    board = {}
    for name, rule in policy.get('board_requires', {}).items():
        if module_name(name) != name or name not in modules or not rule.get('reason', '').strip():
            raise ValueError(f'invalid board dependency rule: {name}')
        board[name] = [module_name(n) for n in rule['modules']]
    selected, builtin_used, graph, edges = set(), set(), {}, []
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name in builtins:
            builtin_used.add(name)
            continue
        if name not in modules:
            raise ValueError(f'missing required module: {name}')
        if name in selected:
            continue
        selected.add(name)
        graph.setdefault(name, set())
        meta = modules[name]
        soft = softdeps(meta.get('softdep', []))
        requirements = [('hard', module_name(n), True) for n in meta['depends']]
        requirements += [('soft-pre', n, True) for n in soft['pre']]
        requirements += [('soft-post', n, False) for n in soft['post']]
        requirements += [('board', n, True) for n in board.get(name, [])]
        for kind, other, before in requirements:
            if other in builtins:
                if not before:
                    raise ValueError(f'{name}: builtin {other} cannot load after a module')
                builtin_used.add(other)
                continue
            if other not in modules:
                raise ValueError(f'{name}: missing {kind} provider {other}')
            earlier, later = (other, name) if before else (name, other)
            graph.setdefault(later, set()).add(earlier)
            graph.setdefault(earlier, set())
            edges.append({'before': earlier, 'after': later, 'kind': kind})
            pending.append(other)
    owners = {}
    reasons = {}
    for item in policy['ownership']:
        name = module_name(item['name'])
        if name in owners:
            raise ValueError(f'duplicate normalized owner: {name}')
        if item.get('source') != 'source-build' or item['partition'] not in PARTITIONS:
            raise ValueError(f'{name}: invalid owner/source; stock modules are not accepted')
        if not item.get('reason', '').strip():
            raise ValueError(f'{name}: ownership rationale missing')
        owners[name], reasons[name] = item['partition'], item['reason']
    if selected != owners.keys():
        raise ValueError(f'ownership must match dependency closure; missing={sorted(selected - owners.keys())}, '
                         f'extra={sorted(owners.keys() - selected)}')
    for edge in edges:
        a, b = edge['before'], edge['after']
        if PARTITIONS.index(owners[a]) > PARTITIONS.index(owners[b]):
            raise ValueError(f'load-stage inversion: {b} in {owners[b]} needs {a} in {owners[a]} first')
    sorter = TopologicalSorter(graph)
    try:
        sorter.prepare()
        order = []
        ready = []
        while sorter.is_active():
            ready.extend(sorter.get_ready())
            # Earlier mount stages always load first, including unrelated nodes.
            ready.sort(key=lambda n: (PARTITIONS.index(owners[n]), n))
            name = ready.pop(0)
            order.append(name)
            sorter.done(name)
    except CycleError as error:
        raise ValueError('hard/soft/board dependency cycle: ' + ' -> '.join(error.args[1])) from error
    entries, destinations = [], set()
    for name in order:
        item = modules[name]
        basename = Path(item['path']).name
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*\.ko', basename):
            raise ValueError(f'{name}: invalid module basename')
        relative = f'{owners[name]}/lib/modules/{basename}'
        if relative in destinations:
            raise ValueError(f'duplicate destination: {relative}')
        destinations.add(relative)
        entries.append({'name': name, 'partition': owners[name], 'source': item['path'],
                        'destination': relative, 'sha256': item['sha256'], 'reason': reasons[name]})
    return {'schema_version': 1, 'status': 'partition_plan_passed',
            'profile': policy['profile'], 'boot_mode': 'normal',
            'complete_device': False, 'flashable': False, 'release': verification['release'],
            'selected_module_count': len(selected), 'roots': roots,
            'partitions': {p: [n for n in order if owners[n] == p] for p in PARTITIONS},
            'entries': entries, 'ordering_edges': edges,
            'builtin_dependencies': sorted(builtin_used),
            'declared_firmware': sorted({f for n in selected for f in modules[n].get('firmware', [])}),
            'unverified': ['Firmware files, calibration and runtime requests',
                           'Complete device driver coverage, HALs and probe order',
                           'Android init stage execution, mount visibility and depmod output',
                           'Module signing, GKI policy, runtime CFI/BTF and hardware']}


def stage_plan(report, output):
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('stage destination must not exist')
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=output.name + '-', dir=output.parent))
    try:
        by_name = {}
        for entry in report['entries']:
            source = Path(entry['source'])
            if digest(source) != entry['sha256']:
                raise ValueError(f'module changed after verification: {entry["name"]}')
            dst = temp / entry['destination']
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dst)
            if digest(dst) != entry['sha256']:
                raise ValueError(f'copied module hash mismatch: {entry["name"]}')
            by_name[entry['name']] = dst.name
        for partition, names in report['partitions'].items():
            directory = temp / partition / 'lib/modules'
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'modules.load.candidate').write_text(''.join(by_name[n] + '\n' for n in names))
        (temp / 'plan.json').write_text(json.dumps(report, indent=2) + '\n')
        (temp / 'README.txt').write_text(
            'Source module partition qualification only; NOT an installer or complete ROM.\n'
            'modules.load.candidate is a reviewed-graph candidate, not an Android init configuration.\n'
            'Do not replace stock modules or copy these directories into a ROM without completing\n'
            'device coverage, init/mount policy, depmod, firmware, signature and probe validation.\n')
        manifest = {str(p.relative_to(temp)): {'size': p.stat().st_size, 'sha256': digest(p)}
                    for p in sorted(temp.rglob('*')) if p.is_file()}
        (temp / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        temp.rename(output)
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-out', required=True, type=Path)
    parser.add_argument('--module-stage', required=True, type=Path)
    parser.add_argument('--policy', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--stage', type=Path, help='new qualification directory; never a ROM partition')
    args = parser.parse_args()
    try:
        kout, external = args.kernel_out.resolve(), args.module_stage.resolve()
        inputs = check_build_inputs(kout, external)
        builtin_path = kout / 'modules.builtin'
        build = json.loads((external / 'build.json').read_text())
        if build['kernel_inputs'].get(str(builtin_path)) != digest(builtin_path):
            raise ValueError('unrecorded/stale modules.builtin; rebuild the external profile')
        builtins = {module_name(Path(n).stem) for n in builtin_path.read_text().splitlines()}
        verification = verify(kout, external)
        report = resolve(verification, json.loads(args.policy.read_text()), builtins)
        report['kernel_input_sha256'] = {**inputs, 'modules.builtin': digest(builtin_path)}
        report['policy_sha256'] = digest(args.policy)
        if args.stage:
            stage = args.stage.resolve()
            if any(stage == p or p in stage.parents for p in (kout, external, Path(__file__).resolve().parents[1])):
                raise ValueError('stage output must be outside source and build trees')
            stage_plan(report, args.stage)
    except (OSError, ValueError, KeyError, TypeError, struct.error) as error:
        parser.exit(1, f'FAIL: {error}\n')
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(f'PASS: {report["selected_module_count"]} source modules; hard/soft/board dependencies and partition stages; NOT boot-qualified')


if __name__ == '__main__':
    main()
