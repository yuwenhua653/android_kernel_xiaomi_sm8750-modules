# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_annibale_os4_media import convert, verify_assets


class MediaInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root/'repo'; self.repo.mkdir()
        self.dump = self.root/'dump'; self.dump.mkdir()
        old, new = 'vendor/etc/display/model.dlc', 'odm/etc/display/model.dlc'
        keep = ['odm/firmware/vpu35_4v.mbn', 'odm/firmware/vpu35_4v_unsigned.mbn']
        remove = ['odm/firmware/vpu33_4v.mbn', 'odm/firmware/vpu33_4v_unsigned.mbn']
        self.profile = {'firmware_label':'OS4.0.6.0.XPKCNXM', 'incremental':'OS4.0.6.0.XPKCN',
            'relocations':{old:new}, 'retained_sun_firmware':keep, 'absent_other_platform_firmware':remove, 'files':{}}
        self.text = '\n'.join([old]+remove+keep+['# preserve','vendor/bin/keep',''])
        for name in [new]+keep:
            path=self.dump/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'asset')
            self.profile['files'][name]={'size':5,'sha256':hashlib.sha256(b'asset').hexdigest()}
        for part,name in [('vendor','build.prop'),('odm','etc/build.prop')]:
            path=self.dump/part/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(f'ro.{part}.build.version.incremental=OS4.0.6.0.XPKCN\n')
        source=self.repo/'sun.c';source.write_text('.fwname = "vpu35_4v",\n')
        self.profile['video_source']={'path':'sun.c','fwname':'vpu35_4v','sha256':hashlib.sha256(source.read_bytes()).hexdigest()}

    def test_moves_install_destination_and_preserves_sun_firmware(self):
        verify_assets(self.dump,self.profile,self.repo)
        after=convert(self.text,self.profile)
        self.assertNotIn('vendor/etc/display/model.dlc',after)
        self.assertIn('odm/etc/display/model.dlc',after)
        self.assertNotIn('vpu33',after)
        self.assertIn('odm/firmware/vpu35_4v.mbn',after)
        self.assertTrue(after.endswith('# preserve\nvendor/bin/keep\n'))

    def test_existing_destination_and_changed_flags_rejected(self):
        for text in (self.text+'odm/etc/display/model.dlc\n',self.text.replace('vendor/etc/display/model.dlc','vendor/etc/display/model.dlc;EXTRACT_ONLY')):
            with self.assertRaises(ValueError):convert(text,self.profile)

    def test_comments_ending_in_old_paths_are_preserved(self):
        comment = '# moved from vendor/etc/display/model.dlc\n# old odm/firmware/vpu33_4v.mbn\n'
        self.assertTrue(convert(self.text+comment,self.profile).endswith(comment))

    def test_missing_retained_sun_firmware_rejected(self):
        with self.assertRaisesRegex(ValueError,'retain'):
            convert(self.text.replace('odm/firmware/vpu35_4v.mbn\n',''),self.profile)

    def test_hash_corruption_rejected(self):
        (self.dump/'odm/etc/display/model.dlc').write_bytes(b'other')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):verify_assets(self.dump,self.profile,self.repo)

    def test_wrong_build_or_changed_platform_rejected(self):
        (self.repo/'sun.c').write_text('.fwname = "vpu33_4v",\n')
        with self.assertRaisesRegex(ValueError,'platform source'):verify_assets(self.dump,self.profile,self.repo)
        (self.dump/'vendor/build.prop').write_text('ro.vendor.build.version.incremental=OS3\n')
        with self.assertRaisesRegex(ValueError,'build mismatch'):verify_assets(self.dump,self.profile,self.repo)

    def test_old_asset_presence_or_symlink_rejected(self):
        path=self.dump/'vendor/etc/display/model.dlc';path.parent.mkdir(parents=True)
        path.symlink_to('/absent-android-file')
        with self.assertRaisesRegex(ValueError,'unexpectedly present'):verify_assets(self.dump,self.profile,self.repo)

    def test_new_asset_symlink_rejected(self):
        path=self.dump/'odm/etc/display/model.dlc';path.unlink();path.symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError,'unsafe media'):verify_assets(self.dump,self.profile,self.repo)
