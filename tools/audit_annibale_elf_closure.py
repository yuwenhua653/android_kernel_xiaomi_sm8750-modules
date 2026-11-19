#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check ARM64 DT_NEEDED closures and versioned dynamic imports (pyelftools).

This is an offline symbol check, not a linker namespace, C++ layout or runtime
ABI qualification. Library paths must describe the intended target, never host
libraries. Weak undefined symbols may legitimately remain unresolved.
"""
import argparse
import hashlib
import json
from pathlib import Path

from annibale_ramdisk import require


def inspect(path):
    from elftools.elf.elffile import ELFFile
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        require(elf.elfclass == 64 and elf.little_endian and elf['e_machine'] == 'EM_AARCH64',
                'not an ARM64 ELF: ' + str(path))
        dynamic = elf.get_section_by_name('.dynamic')
        symbols = elf.get_section_by_name('.dynsym')
        require(dynamic is not None and symbols is not None, 'not a dynamic ELF: ' + str(path))
        needed = [tag.needed for tag in dynamic.iter_tags() if tag.entry.d_tag == 'DT_NEEDED']
        sonames = [tag.soname for tag in dynamic.iter_tags() if tag.entry.d_tag == 'DT_SONAME']
        versions = {}
        section = elf.get_section_by_name('.gnu.version_r')
        if section:
            for _, auxes in section.iter_versions():
                for aux in auxes:
                    versions[aux['vna_other'] & 0x7fff] = aux.name
        section = elf.get_section_by_name('.gnu.version_d')
        if section:
            for definition, auxes in section.iter_versions():
                versions[definition['vd_ndx']] = next(auxes).name
        indices = elf.get_section_by_name('.gnu.version')
        imports, exports = [], []
        for i, symbol in enumerate(symbols.iter_symbols()):
            if not symbol.name:
                continue
            index = indices.get_symbol(i)['ndx'] if indices else 'VER_NDX_GLOBAL'
            hidden = isinstance(index, int) and bool(index & 0x8000)
            if isinstance(index, int) and index & 0x7fff > 1:
                require(index & 0x7fff in versions, 'unknown ELF version index')
                version = versions[index & 0x7fff]
            else:
                version = None
            binding = symbol['st_info']['bind']
            if symbol['st_shndx'] == 'SHN_UNDEF':
                imports.append((symbol.name, version, binding == 'STB_WEAK'))
            elif binding in ('STB_GLOBAL', 'STB_WEAK', 'STB_GNU_UNIQUE') and symbol['st_other']['visibility'] in ('STV_DEFAULT', 'STV_PROTECTED'):
                exports.append((symbol.name, version))
                if not hidden:
                    exports.append((symbol.name, None))
        return {'needed': needed, 'soname': sonames[0] if sonames else path.name,
                'imports': imports, 'exports': set(exports),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def closure_for(root, objects):
    closure, queue = set(), [root]
    while queue:
        name = queue.pop(0)
        if name in closure:
            continue
        require(name in objects, 'missing DT_NEEDED provider: ' + name)
        closure.add(name)
        queue.extend(objects[name]['needed'])
    return closure


def check(root, objects):
    closure = closure_for(root, objects)
    missing, weak, count = [], [], 0
    for name in sorted(closure):
        # Do not let an unrelated provider (or another namespace's libc++)
        # satisfy a dependency by putting every selected export in one pool.
        available = set().union(*(objects[n]['exports'] for n in closure_for(name, objects)))
        for symbol, version, optional in objects[name]['imports']:
            count += 1
            if (symbol, version) not in available:
                (weak if optional else missing).append({'object': name, 'symbol': symbol, 'version': version})
    return {'root': root, 'closure': sorted(closure), 'imports_checked': count,
            'missing_strong': missing, 'unresolved_weak': weak}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--binary', type=Path, action='append', required=True)
    ap.add_argument('--library-dir', type=Path, action='append', default=[])
    ap.add_argument('--loader', type=Path, help='Target runtime linker64, if referenced as ld-android.so')
    ap.add_argument('--provider-map', type=Path, help='Explicit scoped providers: key -> {path, needed: {SONAME: key}}')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    objects, paths = {}, {}
    if args.provider_map:
        require(not args.library_dir and args.loader is None, 'choose either a provider map or flat directories')
        for name, spec in json.loads(args.provider_map.read_text()).items():
            p = Path(spec['path'])
            item = inspect(p)
            require(set(item['needed']) == set(spec['needed']), 'provider map dependency drift: ' + name)
            item['needed'] = [spec['needed'][n] for n in item['needed']]
            objects[name], paths[name] = item, str(p)
        for p in args.binary:
            require(p.name in paths and Path(paths[p.name]).resolve() == p.resolve(), 'root binary map mismatch')
    else:
        require(args.library_dir, 'library directories or a scoped provider map required')
        for p in [*args.binary, *([args.loader] if args.loader else []),
                  *(p for d in args.library_dir for p in d.glob('*.so'))]:
            item = inspect(p)
            name = item['soname']
            require(name not in objects or objects[name]['sha256'] == item['sha256'], 'ambiguous provider: ' + name)
            objects[name], paths[name] = item, str(p)
    results = [check(p.name, objects) for p in args.binary]
    report = {'results': results, 'objects': {n: {'sha256': v['sha256'], 'path': paths[n], 'needed': v['needed']}
              for n, v in sorted(objects.items())}, 'runtime_verified': False, 'linker_namespaces_verified': False}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    require(not any(r['missing_strong'] for r in results), 'unresolved strong symbols; inspect report')
    print('PASS: ARM64 versioned symbol closures; runtime and namespaces unverified')


if __name__ == '__main__':
    main()
