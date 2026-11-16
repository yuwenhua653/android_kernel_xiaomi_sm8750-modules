#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check exact OS4 audio assets read-only; never generate calibration or flash.

Header/CRC checks follow the imported TfaContainer_t and SIPA_PARAM_FW formats.
They do not interpret all firmware instructions or establish DSP/HAL compatibility.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import xml.etree.ElementTree as ET
import zlib


def tfa_header(data):
    if len(data) < 46 or data[:2] != b'PM':
        raise ValueError('invalid TFA container header')
    size, crc = struct.unpack_from('<II', data, 6)
    devices, profiles = struct.unpack_from('<HH', data, 40)
    if size != len(data) or not profiles or devices != 2:
        raise ValueError('unexpected TFA length/device/profile count')
    if data[2:6] != b'3_01' or zlib.crc32(data[14:]) != crc:
        raise ValueError('TFA container revision/CRC mismatch')
    return {'header_crc_checked': True, 'devices': devices, 'profile_count': profiles,
            'version': '3_01', 'full_descriptor_validation': False}


def sia_header(data):
    # Four channels; 8 + 4*4 + 4*12 + 4*28 + 4 bytes, packed in sipa_parameter.h.
    header_size = 188
    if len(data) < header_size:
        raise ValueError('truncated SIA header')
    crc, version = struct.unpack_from('<II', data)
    channels = struct.unpack_from('<4I', data, 8)
    size, = struct.unpack_from('<I', data, 184)
    if version != 0x10005 or size != len(data) - header_size:
        raise ValueError('SIA version/data length mismatch')
    if channels != (1, 1, 0, 0) or zlib.crc32(data[4:]) != crc:
        raise ValueError('SIA channel/CRC mismatch')
    for channel in range(2):
        offset, count, stride = struct.unpack_from('<3I', data, 24 + channel * 12)
        if not count or not stride or offset + count * stride > size:
            raise ValueError('SIA chip table escapes firmware data')
    return {'header_crc_checked': True, 'version': '1.0.5',
            'enabled_channels': [0, 1], 'chip_table_bounds_checked': True,
            'full_register_program_validation': False}


def check(odm_root, manifest, variant):
    if variant not in ('tfa', 'sia') or manifest.get('schema_version') != 1:
        raise ValueError('unsupported asset manifest or amplifier family')
    root = odm_root.resolve()
    files = {}
    for item in manifest['files']:
        if variant not in item['variants']:
            continue
        relative = PurePosixPath(item['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('asset path escapes ODM root')
        path = root / relative
        if not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError(f'missing/escaping audio asset: {relative}')
        if path.stat().st_size != item['size']:
            raise ValueError(f'audio asset size mismatch: {relative}')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != item['sha256']:
            raise ValueError(f'audio asset hash mismatch: {relative}')
        files[str(relative)] = {'size': item['size'], 'sha256': digest}
    firmware = 'firmware/tfa98xx.cnt' if variant == 'tfa' else 'firmware/sipa.bin'
    if firmware not in files:
        raise ValueError('selected firmware is not pinned in manifest')
    parsed = (tfa_header if variant == 'tfa' else sia_header)((root / firmware).read_bytes())
    resource = 'etc/audio/sku_sun/resourcemanager_sun_mtp.xml'
    overlay = 'etc/audio/sku_sun/mixer_paths_overlay_static.xml'
    if resource not in files or overlay not in files:
        raise ValueError('audio XML contracts are not pinned in manifest')
    tree = ET.parse(root / resource)
    contracts = {
        'PAL_DEVICE_OUT_SPEAKER': ('TDM-LPAIF-RX-SECONDARY', '2'),
        'PAL_DEVICE_OUT_HANDSET': ('TDM-LPAIF-RX-SECONDARY', '1'),
        'PAL_DEVICE_IN_VI_FEEDBACK': ('TDM-LPAIF-TX-SECONDARY', '2'),
    }
    backends = {}
    for device, (backend, channels) in contracts.items():
        matches = [n for n in tree.iter() if n.tag in ('in-device', 'out-device')
                   and n.findtext('id') == device]
        if len(matches) != 1:
            raise ValueError(f'missing/ambiguous PAL device {device}')
        node = matches[0]
        expected = {'back_end_name': backend, 'channels': channels,
                    'samplerate': '48000', 'bit_width': '32'}
        if any(node.findtext(k) != v for k, v in expected.items()):
            raise ValueError(f'PAL backend contract mismatch: {device}')
        backends[device] = expected
    controls = {n.get('name') for n in ET.parse(root / overlay).iter('ctl')}
    required = ({'TFA Profile', 'tfa98xx_spksw_gpio_switch'} if variant == 'tfa' else
                {f'{side} {control}' for side in ('SpkrLeft', 'SpkrRight')
                 for control in ('Sipa Audio Scene', 'Sipa Mute')} |
                {'SpkrLeft sia91xx_spk_sw_gpio_switch', 'SpkrRight Sipa Power'})
    if not required <= controls:
        raise ValueError('selected amplifier mixer controls missing from stock overlay')
    return {'status': 'pinned_assets_and_selected_contracts_passed', 'variant': variant,
            'firmware_label': manifest['firmware_label'], 'files': files,
            'firmware_header': parsed, 'pal_backends': backends,
            'referenced_mixer_controls': sorted(required),
            'boot_compatible': False, 'runtime_audio_verified': False,
            'unverified': ['Actual amplifier population and live ALSA controls',
                           'Firmware lookup paths and DSP binaries/topology',
                           'Speaker protection and per-device persist calibration',
                           'HAL binary ABI, SELinux, audio routing and power behavior']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--odm-root', required=True, type=Path)
    parser.add_argument('--variant', required=True, choices=('tfa', 'sia'))
    parser.add_argument('--manifest', type=Path, default=Path(__file__).resolve().parents[1] /
                        'Documentation/xiaomi/annibale-os4-audio-assets.json')
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    try:
        report = check(args.odm_root, json.loads(args.manifest.read_text()), args.variant)
    except (OSError, ValueError, KeyError, TypeError, struct.error, ET.ParseError) as error:
        report = {'status': 'blocked', 'variant': args.variant, 'error': str(error),
                  'boot_compatible': False, 'runtime_audio_verified': False}
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(report['status'] + '; runtime audio unverified')
    return 1 if report['status'] == 'blocked' else 0


if __name__ == '__main__':
    raise SystemExit(main())
