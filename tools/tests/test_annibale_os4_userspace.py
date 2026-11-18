# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare_annibale_os4_userspace import convert, digest, replacement_rules


class UserspaceMigrationTests(unittest.TestCase):
    def setUp(self):
        self.files={'proprietary-files.txt':
            'system_ext/app/AtFwd2/AtFwd2.apk\nsystem_ext/lib64/wfd-V1.so\nodm/lib64/anchor.so\n'
            'vendor/lib64/wfd-V1.so;MODULE_SUFFIX=_vendor\n# comment system_ext/lib64/wfd-V1.so\n',
            'extract-files.py':'''blob_fixups: dict = {
    (
        'odm/lib64/libcom.xiaomi.grallocutils.so',
    ): blob_fixup().replace_needed('libui.so', 'libui-xiaomi.so'),
    (
        'odm/lib64/libdither.so',
    ): blob_fixup().replace_needed('android.hardware.sensors-V2-ndk.so', 'android.hardware.sensors-V3-ndk.so'),
}
'''}
        self.profile={'input_sha256':{},
            'relocations':{'system_ext/app/AtFwd2/AtFwd2.apk':'system_ext/app/atfwd/atfwd.apk',
                           'system_ext/lib64/wfd-V1.so':'system_ext/lib64/wfd-V2.so'},
            'add_after':{'odm/lib64/libcameraopt_stub.so':'odm/lib64/anchor.so',
                         'odm/lib64/libdynamicelvss.so':'odm/lib64/anchor.so'},
            'fixups':{'odm/lib64/libcameraopt_stub.so':{'libui.so':'libui-xiaomi.so'},
                      'odm/lib64/libdynamicelvss.so':{'android.hardware.sensors-V2-ndk.so':'android.hardware.sensors-V3-ndk.so'}}}
        self.pin()

    def pin(self):
        self.profile['input_sha256']={n:digest(t.encode()) for n,t in self.files.items()}

    def test_moves_only_system_interface_and_preserves_comments(self):
        after=convert(self.files,self.profile)
        self.assertIn('system_ext/lib64/wfd-V2.so\n',after['proprietary-files.txt'])
        self.assertIn('vendor/lib64/wfd-V1.so;MODULE_SUFFIX=_vendor\n',after['proprietary-files.txt'])
        self.assertIn('# comment system_ext/lib64/wfd-V1.so',after['proprietary-files.txt'])
        for name, pairs in self.profile['fixups'].items():
            self.assertEqual(replacement_rules(after['extract-files.py'],name),[list(p) for p in pairs.items()])

    def test_changed_input_or_repeated_application_rejected(self):
        after=convert(self.files,self.profile)
        with self.assertRaisesRegex(ValueError,'unreviewed input'):convert(after,self.profile)
        self.files['extract-files.py']+='\n# drift\n'
        with self.assertRaisesRegex(ValueError,'unreviewed input'):convert(self.files,self.profile)

    def test_new_destination_conflict_rejected_even_if_repinned(self):
        self.files['proprietary-files.txt']+='system_ext/lib64/wfd-V2.so\n';self.pin()
        with self.assertRaisesRegex(ValueError,'relocation owner'):convert(self.files,self.profile)

    def test_added_library_conflict_rejected(self):
        self.files['proprietary-files.txt']+='odm/lib64/libcameraopt_stub.so\n';self.pin()
        with self.assertRaisesRegex(ValueError,'added owner'):convert(self.files,self.profile)

    def test_changed_group_semantics_rejected(self):
        self.files['extract-files.py']=self.files['extract-files.py'].replace('libui-xiaomi.so','libui-wrong.so');self.pin()
        with self.assertRaisesRegex(ValueError,'fixup chain differs'):convert(self.files,self.profile)

    def test_multiple_fixup_owners_rejected(self):
        text="blob_fixups: dict = {'x': blob_fixup(), ('x','y'): blob_fixup()}"
        with self.assertRaisesRegex(ValueError,'duplicate fixup owner'):replacement_rules(text,'x')

    def test_nonreplacement_operation_rejected(self):
        with self.assertRaisesRegex(ValueError,'unreviewed selected fixup'):
            replacement_rules("blob_fixups: dict = {'x': blob_fixup().add_needed('y')}",'x')
