# SPDX-License-Identifier: GPL-2.0-only
import struct
import tempfile
from pathlib import Path
import unittest
from annibale_module_parameters import module_parameters
from check_annibale_vendor_runtime import check_module_actions


def fixture(path, *, permission=0o644, reltype=257, symbol=1, addend=0,
            missing=False, duplicate=False, name=b'con_mode\0', short=False):
    labels = ['', '.shstrtab', '.rodata', '.symtab', '.strtab', '__param', '.rela__param']
    strings = ('\0'.join(labels)+'\0').encode()
    symbols = bytes(24)+struct.pack('<IBBHQQ', 0, 3, 0, 2, 0, 0)
    param = bytearray(40)
    struct.pack_into('<H',param,24,permission)
    relocation = struct.pack('<QQq', 0, (symbol<<32)|reltype, addend)
    payloads=[b'', strings, name, symbols, b'\0', bytes(param[:-1] if short else param),
              b'' if missing else relocation*(2 if duplicate else 1)]
    offset=64; headers=[]
    for i,blob in enumerate(payloads):
        kind=3 if i in (1,4) else 2 if i==3 else 4 if i==6 else 1 if i else 0
        headers.append(struct.pack('<IIQQQQIIQQ',strings.index(labels[i].encode()) if i else 0,
            kind,0,0,offset,len(blob),4 if i==3 else 3 if i==6 else 0,5 if i==6 else 0,8,24 if i in (3,6) else 0))
        offset+=len(blob)
    elf=struct.pack('<16sHHIQQQIHHHHHH',b'\x7fELF\x02\x01\x01'+bytes(9),1,183,1,0,0,offset,0,64,0,0,64,7,1)
    path.write_bytes(elf+b''.join(payloads)+b''.join(headers))


class ParameterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'fixture.ko'

    def test_callback_without_modinfo_is_found(self):
        fixture(self.path)
        self.assertEqual(module_parameters(self.path),{'con_mode':{'permission':0o644,'source':'__param'}})

    def test_read_only_permission_preserved(self):
        fixture(self.path,permission=0o444)
        self.assertEqual(module_parameters(self.path)['con_mode']['permission'],0o444)

    def test_section_symbol_addend(self):
        fixture(self.path,name=b'prefix\0con_mode\0',addend=7)
        self.assertIn('con_mode',module_parameters(self.path))

    def test_reject_bad_relocation_and_symbol(self):
        for args in ({'reltype':258},{'symbol':99},{'addend':-1},{'addend':999},
                     {'missing':True},{'duplicate':True},{'short':True},
                     {'name':b'no terminator'},{'permission':0o1000}):
            with self.subTest(args=args):
                fixture(self.path,**args)
                with self.assertRaises(ValueError):module_parameters(self.path)


class FactoryWriteTests(unittest.TestCase):
    def check(self,permission=0o644,preloaded=True,ready=True,value='5',present=True):
        inv={'qca_cld3_kiwi_v2':{'partition':'vendor_dlkm','preloaded':preloaded,
             'parameters':['con_mode'],'parameter_metadata':{'con_mode':{'permission':permission}}}} if present else {}
        text='on property:vendor.wifi.ftmd.load=true'+(' && property:vendor.all.modules.ready=1' if ready else '')+'\n'
        text+='    write /sys/module/qca_cld3_kiwi_v2/parameters/con_mode '+value+'\n'
        return check_module_actions({'device.rc':text},inv)

    def test_factory_callback_checked(self):
        self.assertFalse(self.check()['issues'])
        self.assertEqual(self.check()['actions'][0]['action'],'write_parameter')

    def test_wrong_permissions_order_mode_or_provider_blocked(self):
        for args in ({'permission':0o444},{'preloaded':False},{'ready':False},{'value':'99'},{'present':False}):
            with self.subTest(args=args):self.assertTrue(self.check(**args)['issues'])

    def test_other_sysfs_writes_remain_explicitly_unreviewed(self):
        result=check_module_actions({'x.rc':'on boot\n    write /sys/module/other/parameters/foo 1\n'}, {})
        self.assertEqual(len(result['other_parameter_writes_unreviewed']),1)

    def test_selinux_prefix_does_not_grant_sibling_callbacks(self):
        repo=Path(__file__).resolve().parents[2]
        patch=(repo/'Documentation/xiaomi/patches/annibale-native-wifi-factory.patch').read_text()
        rules=[line[1:].split() for line in patch.splitlines() if line.startswith('+genfscon sysfs ')]
        def label(path):
            matches=[r for r in rules if path.startswith(r[2])]
            return max(matches,key=lambda r:len(r[2]))[3]
        prefix='/module/qca_cld3_kiwi_v2/parameters/'
        self.assertEqual(label(prefix+'con_mode'),'u:object_r:vendor_sysfs_annibale_wlan_mode:s0')
        for name in ('con_mode_ftm','con_mode_epping'):
            self.assertEqual(label(prefix+name),'u:object_r:sysfs:s0')

    def test_mission_mode_restore(self):
        text='on property:vendor.wifi.ftmd.load=false && property:vendor.all.modules.ready=1\n    write /sys/module/qca_cld3_kiwi_v2/parameters/con_mode 0\n'
        inv={'qca_cld3_kiwi_v2':{'partition':'vendor_dlkm','preloaded':True,
            'parameters':['con_mode'],'parameter_metadata':{'con_mode':{'permission':0o644}}}}
        self.assertFalse(check_module_actions({'x.rc':text},inv)['issues'])


if __name__=='__main__':unittest.main()
