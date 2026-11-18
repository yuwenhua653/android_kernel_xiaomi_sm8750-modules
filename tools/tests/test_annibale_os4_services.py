# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare_annibale_os4_services import convert, digest, verify_manifest


class ServiceMigrationTests(unittest.TestCase):
    def setUp(self):
        self.before={'proprietary-files.txt':'vendor/bin/old\nvendor/etc/init/old.rc\nsystem_ext/lib64/old.so\nsystem_ext/lib64/retired.so;SYMLINK=system_ext/app/ims/lib/old.so\nvendor/bin/keep\n',
                     'contexts':'/vendor/bin/old u:object_r:old_exec:s0\n',
                     'services':'old.IFoo/default u:object_r:old_service:s0\n'}
        self.templates={'new.te':'type new_domain, domain;\n'}
        self.profile={'input_sha256':{},'relocations':{'vendor/bin/old':'vendor/bin/new','vendor/etc/init/old.rc':'vendor/etc/init/new.rc','system_ext/lib64/old.so':'system_ext/lib64/new.so'},
                      'retired_entries':['system_ext/lib64/retired.so;SYMLINK=system_ext/app/ims/lib/old.so'],
                      'retained_entries':['vendor/bin/keep'],'add_after':{'vendor/bin/keep':['vendor/lib64/support.so']},
                      'context_replacement':{'file':'contexts','old':'/vendor/bin/old u:object_r:old_exec:s0','new':'/vendor/bin/new u:object_r:new_exec:s0'},
                      'append':{'services':'new.IBar/default u:object_r:new_service:s0\n'},
                      'new_files':{'new.te':{'sha256':digest(self.templates['new.te'].encode())}}}
        self.pin()

    def pin(self):
        self.profile['input_sha256']={n:digest(t.encode()) for n,t in self.before.items()}

    def test_replaces_dependencies_and_removes_obsolete_link_owner(self):
        after=convert(self.before,self.profile,self.templates)
        self.assertEqual(after['proprietary-files.txt'].splitlines(),['vendor/bin/new','vendor/etc/init/new.rc','system_ext/lib64/new.so','vendor/bin/keep','vendor/lib64/support.so'])
        self.assertNotIn('old_exec',after['contexts'])
        self.assertIn('new_service',after['services'])
        self.assertEqual(after['new.te'],self.templates['new.te'])
        self.assertIn('old.so',self.before['proprietary-files.txt'])

    def test_changed_input_and_repeat_application_rejected(self):
        after=convert(self.before,self.profile,self.templates)
        with self.assertRaisesRegex(ValueError,'unreviewed input'):convert(after,self.profile,self.templates)
        self.before['contexts']+='unreviewed\n'
        with self.assertRaisesRegex(ValueError,'unreviewed input'):convert(self.before,self.profile,self.templates)

    def test_existing_replacement_owner_rejected(self):
        self.before['proprietary-files.txt']+='vendor/bin/new\n';self.pin()
        with self.assertRaisesRegex(ValueError,'relocation owner conflict'):convert(self.before,self.profile,self.templates)

    def test_existing_added_owner_rejected(self):
        self.before['proprietary-files.txt']+='vendor/lib64/support.so\n';self.pin()
        with self.assertRaisesRegex(ValueError,'added owner conflict'):convert(self.before,self.profile,self.templates)

    def test_missing_retained_consumer_rejected(self):
        self.before['proprietary-files.txt']=self.before['proprietary-files.txt'].replace('vendor/bin/keep\n','');self.pin()
        with self.assertRaisesRegex(ValueError,'changed required entry'):convert(self.before,self.profile,self.templates)

    def test_duplicate_service_context_rejected(self):
        self.before['services']+='new.IBar/default u:object_r:other_service:s0\n';self.pin()
        with self.assertRaisesRegex(ValueError,'duplicate policy context'):convert(self.before,self.profile,self.templates)

    def test_changed_policy_template_rejected(self):
        self.templates['new.te']+='permissive new_domain;\n'
        with self.assertRaisesRegex(ValueError,'changed policy template'):convert(self.before,self.profile,self.templates)

    def test_aidl_ownership_required_once(self):
        hal='<hal format="aidl"><name>new</name><fqname>IBar/default</fqname></hal>'
        verify_manifest('<manifest>'+hal+'</manifest>',{'new':'IBar/default'})
        for xml in ['<manifest/>','<manifest>'+hal+hal+'</manifest>']:
            with self.assertRaisesRegex(ValueError,'AIDL instance'):verify_manifest(xml,{'new':'IBar/default'})


if __name__=='__main__':unittest.main()
