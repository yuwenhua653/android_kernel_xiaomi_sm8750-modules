# SPDX-License-Identifier: GPL-2.0-only
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from prepare_annibale_native_network import fixup_annibale_native_init
from prepare_annibale_sla_policy import extend
from check_annibale_vendor_runtime import check_module_actions


class NativeFixupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'x.rc';self.path.write_text('on boot\n    old 1\n')
        self.old=self.path.read_bytes();self.new=b'on boot\n    new 2\n'
        self.rule={'input_sha256':hashlib.sha256(self.old).hexdigest(),
                   'output_sha256':hashlib.sha256(self.new).hexdigest(),
                   'replacements':[['old 1','new 2']]}

    def test_exact_fixup_and_reapply_rejected(self):
        fixup_annibale_native_init(None,None,self.path,self.rule)
        self.assertEqual(self.path.read_bytes(),self.new)
        with self.assertRaisesRegex(ValueError,'input changed'):
            fixup_annibale_native_init(None,None,self.path,self.rule)
        self.assertEqual(self.path.read_bytes(),self.new)

    def test_changed_input_or_output_never_written(self):
        self.rule['output_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'output differs'):
            fixup_annibale_native_init(None,None,self.path,self.rule)
        self.assertEqual(self.path.read_bytes(),self.old)
        self.path.write_bytes(self.old+b'# changed\n')
        with self.assertRaisesRegex(ValueError,'input changed'):
            fixup_annibale_native_init(None,None,self.path,self.rule)
        self.assertEqual(self.path.read_bytes(),self.old+b'# changed\n')

    def test_ambiguous_replacement_not_applied(self):
        self.rule['replacements']=[['absent','new']]
        with self.assertRaisesRegex(ValueError,'unique'):
            fixup_annibale_native_init(None,None,self.path,self.rule)
        self.assertEqual(self.path.read_bytes(),self.old)

    def test_sla_plan_is_explicit_and_does_not_change_defaults(self):
        repo=Path(__file__).resolve().parents[2]
        for family in ('tfa','sia'):
            base=json.loads((repo/f'Documentation/xiaomi/annibale-spu-{family}-partitions.json').read_text())
            result=extend(base)
            self.assertNotIn('sla',base['roots']);self.assertIn('sla',result['roots'])
            self.assertFalse(result['experimental_sla']['default_enabled'])
            self.assertFalse(result['experimental_sla']['runtime_verified'])
            self.assertEqual([x['partition'] for x in result['ownership'] if x['name']=='sla'],['vendor_dlkm'])
            with self.assertRaisesRegex(ValueError,'already owned'):extend(result)
        with self.assertRaises(ValueError):extend({'profile':'production'})

    def test_network_parameter_values_and_readiness(self):
        inventory={name:{'partition':'vendor_dlkm','preloaded':True,
                   'parameter_metadata':{param:{'permission':0o644}},'parameters':[param]}
                   for name,param in [('rmnet_perf','rmnet_perf_opt_mode'),('qcom_ramdump','enable_dump_collection')]}
        for name,param,prop,value in [('rmnet_perf','rmnet_perf_opt_mode','persist.vendor.data.perf_ko_load=2','udp'),
                                      ('qcom_ramdump','enable_dump_collection','persist.vendor.ssr.enable_ramdumps=1','1')]:
            text=f'on property:{prop} && property:vendor.all.modules.ready=1\n    write /sys/module/{name}/parameters/{param} {value}\n'
            self.assertFalse(check_module_actions({'x.rc':text},inventory)['issues'])
            self.assertTrue(check_module_actions({'x.rc':text.replace(' && property:vendor.all.modules.ready=1','')},inventory)['issues'])
            self.assertTrue(check_module_actions({'x.rc':text.replace(' '+value+'\n',' wrong\n')},inventory)['issues'])

    def test_legacy_write_is_now_a_blocker(self):
        text='on boot\n    write /sys/module/pil_msa/parameters/pbl_mba_boot_timeout_ms 1\n'
        result=check_module_actions({'x.rc':text},{})
        self.assertEqual(result['issues'][0]['kind'],'unreviewed_parameter_write')
        self.assertEqual(len(result['other_parameter_writes_unreviewed']),1)

    def test_rmmod_remains_unqualified(self):
        inv={'rmnet_shs':{'partition':'vendor_dlkm','preloaded':True,'parameters':[]}}
        text='on property:persist.vendor.data.shs_ko_load=0 && property:vendor.all.modules.ready=1\n    exec u:r:vendor_modprobe:s0 -- /vendor/bin/modprobe -r -d /vendor/lib/modules rmnet_shs\n'
        result=check_module_actions({'x.rc':text},inv)
        self.assertEqual(result['issues'][0]['kind'],'preloaded_module_removal_unqualified')


if __name__=='__main__':unittest.main()
