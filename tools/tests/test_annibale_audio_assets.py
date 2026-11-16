# SPDX-License-Identifier: GPL-2.0-only
import hashlib
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

SCRIPT = Path(__file__).resolve().parents[1] / 'check_annibale_audio_assets.py'
SPEC = importlib.util.spec_from_file_location('audio_assets', SCRIPT)
assets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assets)


def tfa():
    data = bytearray(64)
    data[:6] = b'PM3_01'
    struct.pack_into('<I', data, 6, len(data))
    struct.pack_into('<HH', data, 40, 2, 7)
    struct.pack_into('<I', data, 10, zlib.crc32(data[14:]))
    return data


def sia():
    data = bytearray(204)
    struct.pack_into('<I4I', data, 4, 0x10005, 1, 1, 0, 0)
    struct.pack_into('<3I', data, 24, 0, 1, 8)
    struct.pack_into('<3I', data, 36, 8, 1, 8)
    struct.pack_into('<I', data, 184, 16)
    struct.pack_into('<I', data, 0, zlib.crc32(data[4:]))
    return data


class AudioAssetsTests(unittest.TestCase):
    def test_valid_firmware_headers(self):
        self.assertEqual(assets.tfa_header(tfa())['devices'], 2)
        self.assertEqual(assets.sia_header(sia())['enabled_channels'], [0, 1])

    def test_corrupted_firmware_is_rejected(self):
        for maker, check in ((tfa, assets.tfa_header), (sia, assets.sia_header)):
            data = maker()
            data[-1] ^= 1
            with self.assertRaisesRegex(ValueError, 'CRC'):
                check(data)

    def test_truncation_and_wrong_revision(self):
        for maker, check in ((tfa, assets.tfa_header), (sia, assets.sia_header)):
            with self.assertRaises(ValueError):
                check(maker()[:10])
            with self.assertRaises(ValueError):
                check(maker()[:-1])
        data = sia()
        struct.pack_into('<I', data, 4, 0x10004)
        with self.assertRaisesRegex(ValueError, 'version'):
            assets.sia_header(data)

    def test_crc_valid_table_overflow_is_rejected(self):
        data = sia()
        struct.pack_into('<I', data, 36, 0xffffffff)
        struct.pack_into('<I', data, 0, zlib.crc32(data[4:]))
        with self.assertRaisesRegex(ValueError, 'escapes'):
            assets.sia_header(data)

    def fixture(self, root, backend='TDM-LPAIF-RX-SECONDARY'):
        resource = '<resource_manager>'
        for tag, name, route, channels in (
                ('out-device', 'PAL_DEVICE_OUT_SPEAKER', backend, 2),
                ('out-device', 'PAL_DEVICE_OUT_HANDSET', 'TDM-LPAIF-RX-SECONDARY', 1),
                ('in-device', 'PAL_DEVICE_IN_VI_FEEDBACK', 'TDM-LPAIF-TX-SECONDARY', 2)):
            resource += (f'<{tag}><id>{name}</id><back_end_name>{route}</back_end_name>'
                         f'<channels>{channels}</channels><samplerate>48000</samplerate>'
                         f'<bit_width>32</bit_width></{tag}>')
        resource += '</resource_manager>'
        data = {
            'firmware/tfa98xx.cnt': tfa(),
            'etc/audio/sku_sun/resourcemanager_sun_mtp.xml': resource.encode(),
            'etc/audio/sku_sun/mixer_paths_overlay_static.xml':
                b'<mixer><ctl name="TFA Profile"/><ctl name="tfa98xx_spksw_gpio_switch"/></mixer>'}
        rows = []
        for name, content in data.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            rows.append({'path': name, 'size': len(content), 'variants': ['tfa'],
                         'sha256': hashlib.sha256(content).hexdigest()})
        return {'schema_version': 1, 'firmware_label': 'fixture', 'files': rows}

    def test_pinned_assets_pass_without_runtime_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = assets.check(root, self.fixture(root), 'tfa')
            self.assertFalse(report['runtime_audio_verified'])
            self.assertFalse(report['boot_compatible'])

    def test_wrong_hash_or_route_blocks_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.fixture(root)
            path = root / 'firmware/tfa98xx.cnt'
            data = bytearray(path.read_bytes())
            data[-1] ^= 1
            path.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                assets.check(root, manifest, 'tfa')
            manifest = self.fixture(root, 'TDM-LPAIF-RX-PRIMARY')
            with self.assertRaisesRegex(ValueError, 'backend contract'):
                assets.check(root, manifest, 'tfa')

    def test_manifest_cannot_escape_odm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.fixture(root)
            manifest['files'][0]['path'] = '../firmware.bin'
            with self.assertRaisesRegex(ValueError, 'escapes'):
                assets.check(root, manifest, 'tfa')


if __name__ == '__main__':
    unittest.main()
