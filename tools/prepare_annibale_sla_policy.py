#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Generate an explicit SLA qualification plan; default source plans stay off."""
import argparse
import copy
import json
from pathlib import Path


def extend(policy):
    if (policy.get('profile') != 'native-source-qualification' or
        policy.get('boot_mode') != 'normal' or policy.get('complete_device') is not False or
        policy.get('audio_variant') not in ('tfa','sia')):
        raise ValueError('expected incomplete native TFA/SIA qualification plan')
    if 'sla' in policy['roots'] or any(o['name']=='sla' for o in policy['ownership']):
        raise ValueError('SLA already owned')
    result=copy.deepcopy(policy)
    result['roots'].append('sla')
    result['ownership'].append({'name':'sla','source':'source-build','partition':'vendor_dlkm',
        'reason':'Explicit experimental SLA qualification; preload before modules.ready; no runtime acceptance claim'})
    result['scope'] += '; experimental SLA included, runtime unverified'
    result['experimental_sla']={'selected':True,'default_enabled':False,'runtime_verified':False,
        'required_before_release':['target MM/proc/netfilter stress','slad statistics semantics','production KMI/signatures','HyperOS and AOSP hardware checks']}
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.exists():ap.error('output exists')
    policy=extend(json.loads(args.base.read_text()))
    args.output.write_text(json.dumps(policy,indent=2)+'\n')
    print('Created experimental SLA qualification plan; not a release or flash approval')


if __name__=='__main__':main()
