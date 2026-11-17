#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Audit enabled Sun power nodes and typed supplier references in final DTBs.

Checks static wiring, not successful probes, cooling operation or suspend entry.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

COMPAT = {'qcom,lpm-cluster-dev': 3, 'qcom,regulator-ocp-notifier': 1,
          'qcom,cpufreq-thermal': 1, 'qcom,tsens-v2': 4,
          'qcom,thermal-pause': 1, 'qcom,cpufreq-cdev': 1,
          'qcom,spmi-adc5-gen3': 1, 'qcom,spmi-temp-alarm': 12,
          'qcom,rpmh-stats-v4': 1, 'qcom,ddr-cooling-device': 1,
          'qcom,devfreq-cdev': 1}
TYPED = {'mboxes': '#mbox-cells', 'clocks': '#clock-cells',
         'power-domains': '#power-domain-cells', 'interconnects': '#interconnect-cells',
         'io-channels': '#io-channel-cells'}
SINGLE = {'nvmem-cells', 'qcom,qmp', 'qcom,devfreq', 'interrupt-parent'}


def require(value, message):
    if not value:
        raise ValueError(message)


def enabled(nodes, path):
    while True:
        if nodes[path].get('status', b'okay\0') not in (b'ok\0', b'okay\0'):
            return False
        if path == '/':
            return True
        path = path.rsplit('/', 1)[0] or '/'


def inspect(tree, cells):
    nodes = tree.nodes
    ph = {cells(p['phandle'])[0]: n for n, p in nodes.items() if 'phandle' in p}
    selected, counts = {}, {}
    for compat, count in COMPAT.items():
        names = [n for n, p in nodes.items() if compat.encode() in p.get('compatible', b'').split(b'\0') and enabled(nodes, n)]
        require(len(names) == count, f'{compat}: expected {count} active nodes, got {len(names)}')
        counts[compat] = len(names)
        selected.update({n: nodes[n] for n in names})
    cpus = {n: p for n, p in nodes.items() if p.get('device_type') == b'cpu\0' and enabled(nodes, n)}
    require(len(cpus) == 8, 'expected eight active SCMI CPUs')
    selected.update(cpus)
    references = {}
    for name, props in selected.items():
        refs = {}
        for key, value in props.items():
            if key not in TYPED and key not in SINGLE and not key.endswith('-supply'):
                continue
            data, index, items = cells(value), 0, []
            while index < len(data):
                require(data[index] in ph, f'{name}:{key}: unresolved provider')
                path = ph[data[index]]
                require(enabled(nodes, path), f'{name}:{key}: disabled provider {path}')
                count_key = TYPED.get(key)
                if count_key:
                    require(count_key in nodes[path], f'{path}: missing {count_key}')
                    count_cells = cells(nodes[path][count_key])
                    require(len(count_cells) == 1, f'{path}: invalid {count_key}')
                    count = count_cells[0]
                else:
                    count = 0
                require(index + count + 1 <= len(data), f'{name}:{key}: truncated provider arguments')
                items.append({'provider': path, 'args': data[index + 1:index + count + 1]})
                index += count + 1
            refs[key] = items
        references[name] = refs
        compat = props.get('compatible', b'').split(b'\0')
        if b'qcom,regulator-ocp-notifier' in compat:
            require(sum(k.endswith('-supply') for k in refs) == 69, 'expected 69 OCP regulator supplies')
            require(len(refs.get('nvmem-cells', [])) == 2, 'OCP needs both SDAM cells')
        if b'qcom,cpufreq-thermal' in compat:
            require(len(refs.get('mboxes', [])) == 2, 'CPU thermal needs two CPUCP mailboxes')
            require(cells(props.get('qcom,policy-cpus', b'')) == [0, 6], 'wrong CPU policy representatives')
        if b'qcom,lpm-cluster-dev' in compat:
            require(len(refs.get('power-domains', [])) == 1, 'LPM needs PSCI cluster domain')
        if b'qcom,ddr-cooling-device' in compat:
            require(len(refs.get('interconnects', [])) == 2, 'DDR cooling needs interconnect endpoints')
        if b'qcom,devfreq-cdev' in compat:
            require(len(refs.get('qcom,devfreq', [])) == 1, 'GPU cooling needs devfreq supplier')
        if name in cpus:
            clocks = refs.get('clocks', [])
            require(len(clocks) == 1 and clocks[0]['args'] in ([0], [1]), 'CPU clock must use SCMI performance domain')
            provider = nodes[clocks[0]['provider']]
            require(cells(provider.get('reg', b'')) == [0x13], 'CPU clock is not SCMI performance protocol 0x13')
    return {'active_nodes': counts, 'cpus': len(cpus), 'references': references}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--devicetrees', type=Path, required=True)
    ap.add_argument('--dt-images', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    args = ap.parse_args()
    sys.path.insert(0, str(args.devicetrees / 'tools'))
    from annibale_fdt import Fdt, cells
    results = {}
    for family in ('tfa', 'sia'):
        for mode in ('default', 'native'):
            for base in ('sun', 'sun-v2', 'sun-tp', 'sun-tp-v2', 'sunp', 'sunp-v2', 'sunp-tp', 'sunp-tp-v2'):
                path = args.dt_images / f'{family}-{mode}' / (base + '.dtb')
                data = path.read_bytes()
                result = inspect(Fdt(data), cells)
                result['sha256'] = hashlib.sha256(data).hexdigest()
                results[str(path.relative_to(args.dt_images))] = result
    args.report.write_text(json.dumps({'status': 'power_dt_passed', 'hardware_verified': False, 'dtbs': results}, indent=2) + '\n')
    print(f'PASS: {len(results)} merged DTBs; power/thermal nodes and typed suppliers; runtime unverified')


if __name__ == '__main__':
    main()
