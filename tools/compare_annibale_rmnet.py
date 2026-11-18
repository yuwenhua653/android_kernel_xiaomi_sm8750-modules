#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare stock/native RMNET metadata, not KMI or runtime compatibility."""
import argparse
import hashlib
import json
from pathlib import Path

from annibale_ramdisk import require
from verify_annibale_modules import module_info

MODULES = ('rmnet_perf', 'rmnet_shs', 'rmnet_offload')
LEGACY_PARAMETERS = ('rmnet_perf_ingress_deag', 'rmnet_perf_opt_mode')


def metadata(path, name):
    require(path.is_file() and not path.is_symlink(), 'missing/symlink module: '+str(path))
    info, _ = module_info(path)
    require(info['name'] == [name], 'unexpected module identity: '+str(path))
    return {'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'parameters':sorted(info.get('parmtype', [])),
            'depends':sorted(filter(None, info['depends'][0].split(','))),
            'vermagic':info['vermagic'][0]}


def compare(stock, native):
    old, new = set(stock['parameters']), set(native['parameters'])
    return {'stock_only_parameters':sorted(old-new), 'native_only_parameters':sorted(new-old),
            'dependencies_equal':stock['depends'] == native['depends'],
            'parameter_types_equal':old == new}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--stock-modules', type=Path, required=True)
    ap.add_argument('--handoff', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    args = ap.parse_args()
    records = {}
    for name in MODULES:
        candidates = list((args.handoff/'modules').glob('*/lib/modules/'+name+'.ko'))
        require(len(candidates) == 1, 'missing/duplicate native module: '+name)
        stock = metadata(args.stock_modules/(name+'.ko'), name)
        native = metadata(candidates[0], name)
        records[name] = {'stock':stock,'native':native, 'comparison':compare(stock,native)}
    perf = records['rmnet_perf']
    legacy = {parameter:{side:parameter in {p.split(':',1)[0] for p in perf[side]['parameters']}
                         for side in ('stock','native')} for parameter in LEGACY_PARAMETERS}
    equal = all(r['comparison']['parameter_types_equal'] and r['comparison']['dependencies_equal']
                for r in records.values())
    result = {'status':'metadata_equal' if equal else 'metadata_differs', 'modules':records,
              'legacy_init_parameters_exported':legacy,
              'runtime_qualified':False, 'kmi_qualified':False, 'init_gate_overridden':False,
              'limitations':['Metadata equality does not establish parameter semantics or live tuning',
                             'RMNET unload/reload lifecycle and traffic behavior require testing',
                             'Stock modules must not be substituted into the OSS handoff based on this check']}
    args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(result['status']+'; runtime/KMI unverified; init gate unchanged')
    return 0 if equal else 1


if __name__ == '__main__':
    raise SystemExit(main())
