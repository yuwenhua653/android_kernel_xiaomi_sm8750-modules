#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile and simulate both QESD policies using pinned Minijail and ARM64 UAPI.

Requires google/minijail c46d08600b8b6548809d37be1964396efde1c3ac
and LineageOS/android_bionic libc/kernel/uapi/asm-arm64/asm/unistd_64.h
with Git blob 41b77d7d8dd38467c3ef80fbde334890f068d8a5.
This runs the compiler/BPF simulator on the host, not QESD on a device.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from annibale_ramdisk import require
from prepare_annibale_qesdsys_source import pinned, sha


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('minijail', 'arm64-header', 'donor', 'prepared-source', 'output'):
        ap.add_argument('--' + name, type=Path, required=True)
    args = ap.parse_args()
    require(not args.output.exists(), 'output already exists')
    revision = subprocess.check_output(['git', '-C', str(args.minijail), 'rev-parse', 'HEAD'], text=True).strip()
    require(revision == 'c46d08600b8b6548809d37be1964396efde1c3ac', 'unreviewed Minijail revision')
    require(not subprocess.check_output(['git', '-C', str(args.minijail), 'status', '--porcelain', '--untracked-files=no']), 'modified Minijail checkout')
    data = args.arm64_header.read_bytes()
    blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    require(blob == '41b77d7d8dd38467c3ef80fbde334890f068d8a5', 'unreviewed ARM64 syscall header')
    numbers = {n: int(v) for n, v in re.findall(r'^#define __NR_(\w+) (\d+)$', data.decode(), re.M)}
    sys.path.insert(0, str(args.minijail.resolve() / 'tools'))
    import arch
    import bpf
    import compiler
    cfg = {'arch_nr': 0xc00000b7, 'arch_name': 'arm64', 'bits': 64, 'syscalls': numbers,
           'constants': {'AF_UNIX': 1, 'PROT_WRITE': 2, 'PROT_EXEC': 4}, 'syscall_groups': {}}
    a = arch.Arch.load_from_json_bytes(json.dumps(cfg).encode())
    repo = Path(__file__).resolve().parents[1]
    profile = json.loads((repo / 'Documentation/xiaomi/annibale-qesd-managers.json').read_text())
    names = profile['seccomp_additions']
    pinned(args.donor, {n: profile['donor_sha256'][n] for n in names})
    pinned(args.prepared_source, {n: profile['output_sha256'][n] for n in names})
    result = {}
    for name, additions in names.items():
        checks = []
        for label, root in [('before', args.donor), ('after', args.prepared_source)]:
            path = root / name
            compiled = compiler.PolicyCompiler(a).compile_file(str(path),
                optimization_strategy=compiler.OptimizationStrategy.BST, kill_action=bpf.KillThread())
            def run(n, values=(), nr=None):
                return bpf.simulate(compiled.instructions, a.arch_nr,
                                    numbers[n] if nr is None else nr, *values)[1]
            changed = {n: run(n) for n in additions}
            require(all(v == ('ALLOW' if label == 'after' else 'KILL_THREAD') for v in changed.values()), 'syscall regression')
            require(run('socket', (1,)) == 'ALLOW' and all(run('socket', (n,)) == 'KILL_THREAD' for n in (2, 10)), 'socket restriction lost')
            for n in ('mmap', 'mprotect'):
                for prot in range(8):
                    require(run(n, (0, 0, prot)) == ('KILL_THREAD' if prot & 6 == 6 else 'ALLOW'), 'W^X regression')
            require(run('read', nr=0x7fffffff) == 'KILL_THREAD', 'default-deny regression')
            require(bpf.simulate(compiled.instructions, 0xc000003e, numbers['read'])[1] == 'KILL_THREAD', 'architecture guard lost')
            require(run('nanosleep') == 'ALLOW', 'existing nanosleep rule lost')
            checks.append({'stage': label, 'instructions': len(compiled.instructions),
                'added_syscall_actions': changed, 'unix_only_socket': True, 'wx_denied': True,
                'unknown_syscall_denied': True, 'wrong_arch_denied': True, 'nanosleep_allowed': True,
                'sha256': sha(path.read_bytes()), 'bpf_sha256': sha(compiled.opcodes)})
        result[name] = checks
    args.output.write_text(json.dumps({'compiler_commit': revision, 'arm64_header_blob': blob,
        'results': result, 'device_execution': False}, indent=2) + '\n')
    print('PASS: both ARM64 policies compiled and simulated; runtime unverified')


if __name__ == '__main__':
    main()
