#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check source-built and retained-stock module paths against one kernel.

Read-only qualification, not a ROM packager or a bootability test. Both paths
are mandatory. An incomplete stock inventory never becomes a combined pass.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from audit_annibale_stock import audit
from verify_annibale_modules import verify


KERNEL_INPUTS = ('.config', 'include/generated/autoconf.h',
                 'include/config/kernel.release', 'Module.symvers', 'vmlinux',
                 'arch/arm64/boot/Image', 'modules.order')
ERRORS = (OSError, ValueError, KeyError, TypeError, UnicodeError, struct.error)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_build_inputs(kernel_out, module_stage):
    """Reject stale kernel artifacts against the external build's snapshot."""
    build = json.loads((module_stage / 'build.json').read_text())
    if (not isinstance(build, dict)
            or build.get('objects_only') is not False or build.get('returncode') != 0
            or build.get('make_returncode') != 0
            or build.get('verification_status') != 'passed'
            or build.get('kernel_inputs_unchanged') is not True):
        raise ValueError('external stage lacks a successful complete build record')
    recorded = build['kernel_inputs']
    if not isinstance(recorded, dict):
        raise ValueError('invalid kernel input hash record')
    result = {}
    for relative in KERNEL_INPUTS:
        path = kernel_out / relative
        actual = digest(path)
        if recorded.get(str(path)) != actual:
            raise ValueError(f'stale/unrecorded kernel build input: {relative}')
        result[relative] = actual
    return result


def combined_status(native, stock):
    if native != 'passed' or stock == 'blocked':
        return 'blocked'
    if stock == 'incomplete_inventory':
        return 'incomplete_inventory'
    if stock != 'no_detected_abi_blocker':
        return 'blocked'
    return 'static_checks_passed'


def check(kernel_out, module_stage, stock_modules):
    kernel_out, module_stage = kernel_out.resolve(), module_stage.resolve()
    native, stock = {}, {}
    try:
        inputs = check_build_inputs(kernel_out, module_stage)
        native = {'status': 'passed', 'kernel_input_sha256': inputs,
                  'verification': verify(kernel_out, module_stage)}
    except ERRORS as error:
        native = {'status': 'blocked', 'error': str(error)}
    # Run even when native fails: a stock pass cannot hide that regression.
    try:
        stock = audit(stock_modules, kernel_out)
    except ERRORS as error:
        stock = {'status': 'blocked', 'error': str(error)}
    ownership = {'policy': 'Separate profiles; never union stock and source module lists.'}
    if native['status'] == 'passed' and 'modules' in stock:
        source_names = set(native['verification']['modules'])
        stock_names = {m['name'] for m in stock['modules']}
        ownership['names_present_in_both_profiles'] = sorted(source_names & stock_names)
        ownership['stock_names_without_built_source_counterpart'] = sorted(stock_names - source_names)
        ownership['note'] = ('Name overlap requires an explicit owner per ROM profile; '
                             'equal names or CRCs do not prove equivalent HAL behavior. '
                             'Missing same-name source outputs are a planning inventory, '
                             'not proof that every stock module is required.')
    return {'schema_version': 1,
            'status': combined_status(native['status'], stock['status']),
            'native_source_modules': native, 'hyperos_stock_modules': stock,
            'module_ownership': ownership,
            'boot_compatibility_verified': False,
            'unverified': ['Complete native ROM driver coverage and HAL contracts',
                           'Stock normal/recovery module selection and load order',
                           'Final GKI symbol policy, signature trust and runtime CFI/BTF',
                           'DTB/DTBO, firmware, boot image assembly and hardware behavior']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-out', type=Path, required=True)
    parser.add_argument('--module-stage', type=Path, required=True)
    parser.add_argument('--stock-modules', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = check(args.kernel_out, args.module_stage, args.stock_modules)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(f'{report["status"]}: native={report["native_source_modules"]["status"]}, '
          f'stock={report["hyperos_stock_modules"]["status"]}; boot unverified')
    return 0 if report['status'] == 'static_checks_passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
