# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare_annibale_vendor import convert
from check_annibale_vendor_runtime import check_services, check_firmware, sections, check_import, check_module_actions
from build_annibale_native_images import check_fstab


def vendor_fixture():
    bp='// Keep this { comment }\ncc_prebuilt_binary { name: "keep", arch: { arm64: { srcs: ["keep"], }, }, }\n'
    mk='PRODUCT_PACKAGES += \\\n    keep \\\n'
    for name in ('system_dlkm_modprobe','vendor_modprobe'):
        bp+=f'sh_binary {{\n    name: "{name}",\n    owner: "xiaomi",\n    src: "proprietary/vendor/bin/{name}.sh",\n    filename: "{name}.sh",\n    soc_specific: true,\n}}\n'
        mk+='    '+name+' \\\n'
    return bp,mk+'    last\n'


def init_fixture():
    text='on early-init\n    exec_start gki.modprobe\n    start vendor.modprobe\n'
    for service,name in (('gki.modprobe','system_dlkm_modprobe.sh'),('vendor.modprobe','vendor_modprobe.sh')):
        text+=f'service {service} /vendor/bin/{name}\n    class main\n    user root\n    group root system\n    disabled\n    oneshot\n    seclabel u:r:vendor_modprobe:s0\n'
    return {'kernel.rc':text,'target.rc':'on post-fs-data\n    wait_for_prop vendor.all.modules.ready 1\n'}


class VendorOwnerTests(unittest.TestCase):
    def test_two_owners_removed_other_modules_byte_preserved(self):
        bp,mk=vendor_fixture();new_bp,new_mk,owners=convert(bp,mk)
        self.assertEqual(set(owners),{'vendor_modprobe','system_dlkm_modprobe'})
        self.assertEqual(new_bp.split('sh_binary')[0].strip(),bp.split('sh_binary')[0].strip())
        self.assertEqual(new_mk,'PRODUCT_PACKAGES += \\\n    keep \\\n    last\n')

    def test_duplicate_owner_rejected(self):
        bp,mk=vendor_fixture();duplicate=bp[bp.index('sh_binary'):]
        with self.assertRaisesRegex(ValueError,'duplicate installed'):convert(bp+duplicate,mk)

    def test_wrong_destination_rejected(self):
        bp,mk=vendor_fixture()
        with self.assertRaisesRegex(ValueError,'destination changed'):
            convert(bp.replace('filename: "vendor_modprobe.sh"','filename: "different.sh"'),mk)

    def test_duplicate_package_rejected(self):
        bp,mk=vendor_fixture()
        with self.assertRaisesRegex(ValueError,'duplicate loader product'):
            convert(bp,mk.replace('    vendor_modprobe \\\n','    vendor_modprobe \\\n    vendor_modprobe \\\n'))

    def test_unreviewed_dynamic_source_rejected(self):
        bp,mk=vendor_fixture()
        with self.assertRaises(ValueError):convert(bp.replace('src: "proprietary/vendor/bin/vendor_modprobe.sh"','src: dynamic_source'),mk)

    def test_copy_owner_not_silently_kept(self):
        bp,mk=vendor_fixture()
        with self.assertRaisesRegex(ValueError,'another loader file owner'):
            convert(bp,mk+'PRODUCT_COPY_FILES += other:$(TARGET_COPY_OUT_VENDOR)/bin/vendor_modprobe.sh\n')


class RuntimeTests(unittest.TestCase):
    def test_serial_services_and_barrier(self):
        self.assertEqual(check_services(init_fixture())['service_owners']['gki.modprobe'],'kernel.rc')

    def test_duplicate_service_rejected(self):
        files=init_fixture();files['duplicate.rc']=files['kernel.rc']
        with self.assertRaisesRegex(ValueError,'duplicate init service'):check_services(files)

    def test_parallel_start_rejected(self):
        files=init_fixture();files['kernel.rc']=files['kernel.rc'].replace('exec_start gki.modprobe','start gki.modprobe')
        with self.assertRaisesRegex(ValueError,'ordering'):check_services(files)

    def test_ready_bypass_rejected(self):
        files=init_fixture();files['bypass.rc']='on init\n    setprop vendor.all.modules.ready 1\n'
        with self.assertRaisesRegex(ValueError,'bypass'):check_services(files)

    def test_changed_selinux_domain_rejected(self):
        files=init_fixture();files['kernel.rc']=files['kernel.rc'].replace('u:r:vendor_modprobe:s0','u:r:init:s0')
        with self.assertRaisesRegex(ValueError,'credentials'):check_services(files)

    def test_continued_service_and_complete_section(self):
        files=init_fixture();files['kernel.rc']=files['kernel.rc'].replace('service gki.modprobe /vendor','service gki.modprobe \\\n    /vendor')
        check_services(files)
        first=next(iter(sections('on init\n    start example\non boot\n    stop example\n')))
        self.assertEqual(first['body'],[['start','example']])

    def test_import_check_tolerates_unrelated_continued_commands(self):
        check_import('import /vendor/example.rc\non init\n    exec -- /vendor/bin/tool \\\n        argument\n', '/vendor/example.rc')

    def test_charger_barrier_recorded_without_qualification(self):
        files=init_fixture();files['charger.rc']='on init && property:ro.boot.mode=charger\n    wait_for_prop vendor.all.modules.ready 1\n'
        report=check_services(files)
        self.assertFalse(report['charger_verified']);self.assertEqual(len(report['ready_barriers']),2)


class FirmwareWiringTests(unittest.TestCase):
    def setUp(self):
        self.fstab=(Path(__file__).resolve().parents[2]/'configs/annibale/native/fstab.qcom').read_text()
        self.ueventd='import /vendor/etc/fw_dir.ueventd.qcom.rc\n'
        self.directories='firmware_directories /vendor/firmware_mnt/image/ /vendor/modem_firmware/image/\n'

    def test_reviewed_wiring(self):
        self.assertFalse(check_firmware(self.ueventd,self.directories,self.fstab)['firmware_bytes_verified'])

    def test_commented_import_is_not_active(self):
        with self.assertRaisesRegex(ValueError,'not imported'):
            check_firmware('# '+self.ueventd,self.directories,self.fstab)

    def test_missing_or_writable_firmware_mount_rejected(self):
        for mount in ('/vendor/firmware_mnt','/vendor/modem_firmware','/vendor/dsp','/vendor/bt_firmware'):
            row=next(l for l in self.fstab.splitlines() if ' '+mount+' ' in l)
            for changed in ('',row.replace(' ro,',' rw,'),row.replace(',slotselect','')):
                with self.subTest(mount=mount,changed=changed),self.assertRaisesRegex(ValueError,'firmware mount'):
                    check_fstab(self.fstab.replace(row,changed))


class ModuleActionTests(unittest.TestCase):
    def setUp(self):
        self.inventory = {'rmnet_perf': {'partition': 'vendor_dlkm',
            'parameters': ['rmnet_perf_knob0'], 'preloaded': True}}

    def check_command(self, command):
        return check_module_actions({'nicmd.rc': 'on property:vendor.example=1\n    '+command+'\n'}, self.inventory)

    def test_supported_module_parameter(self):
        result = self.check_command('exec u:r:vendor_modprobe:s0 -- /vendor/bin/modprobe -d /vendor/lib/modules rmnet_perf rmnet_perf_knob0=Y')
        self.assertEqual(result['issues'], [])
        self.assertFalse(result['runtime_verified'])

    def test_stock_parameter_missing_in_source(self):
        result = self.check_command('exec -- /vendor/bin/modprobe -d /vendor/lib/modules rmnet_perf rmnet_perf_opt_mode="udp"')
        self.assertEqual(result['issues'][0]['kind'], 'unsupported_module_parameter')
        self.assertEqual(result['issues'][0]['parameter'], 'rmnet_perf_opt_mode')

    def test_direct_missing_module_recorded_with_trigger(self):
        result = self.check_command('insmod /vendor/lib/modules/sla.ko')
        self.assertEqual(result['issues'][0]['kind'], 'module_not_packaged')
        self.assertEqual(result['issues'][0]['trigger'], ['on', 'property:vendor.example=1'])

    def test_preloaded_remove_requires_review(self):
        result = self.check_command('exec -- /vendor/bin/modprobe -r -d /vendor/lib/modules rmnet_perf')
        self.assertEqual(result['issues'][0]['kind'], 'preloaded_module_removal_unqualified')

    def test_module_partition_is_checked(self):
        result = self.check_command('insmod /system/lib/modules/rmnet_perf.ko')
        self.assertEqual(result['issues'][0]['kind'], 'module_partition_mismatch')

    def test_unsupported_command_is_not_silently_passed(self):
        result = self.check_command('exec -- /vendor/bin/modprobe --unknown -d /vendor/lib/modules rmnet_perf')
        self.assertEqual(result['issues'][0]['kind'], 'unreviewed_modprobe_option')

    def test_comments_and_loader_service_start_not_module_actions(self):
        files = {'init.rc': '# insmod /vendor/lib/modules/sla.ko\non early-init\n    start vendor.modprobe\n'}
        self.assertEqual(check_module_actions(files, self.inventory)['actions'], [])

    def test_all_modules_with_parameters_is_ambiguous(self):
        result = self.check_command('exec -- /vendor/bin/modprobe -a -d /vendor/lib/modules rmnet_perf rmnet_perf_knob0=Y')
        self.assertEqual(result['issues'][0]['kind'], 'ambiguous_module_parameters')
