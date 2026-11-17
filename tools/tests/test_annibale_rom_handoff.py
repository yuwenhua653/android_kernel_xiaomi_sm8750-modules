# SPDX-License-Identifier: GPL-2.0-only
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_annibale_rom_handoff import convert, HANDOFF_PATH


def reference():
    return {'BoardConfig.mk': 'androidboot.load_modules_parallel=true\n# Kernel prebuilt\nPREBUILT_PATH := old\n# Kernel modules\nOLD_MODULES := old\n# Partitions\nBOARD_INIT_BOOT_IMAGE_PARTITION_SIZE := 8388608\ninclude device/qcom/sepolicy_vndr/SEPolicy.mk\n',
            'device.mk': 'PRODUCT_PACKAGES += existing_service\nPRODUCT_COPY_FILES += $(LOCAL_PATH)/rootdir/etc/fstab.qcom:$(TARGET_COPY_OUT_VENDOR_RAMDISK)/first_stage_ramdisk/fstab.qcom\n',
            'proprietary-files.txt': 'vendor/bin/system_dlkm_modprobe.sh\nvendor/bin/vendor_modprobe.sh\nvendor/etc/init/hw/init.qti.kernel.rc\nvendor/etc/init/hw/init.qti.kernel.target.rc\n',
            'rootdir/Android.bp': 'prebuilt_etc { name: "fstab.qcom", src: "etc/fstab.qcom", vendor: true, }\n'}


class HandoffConversionTests(unittest.TestCase):
    def test_replaces_both_kernel_and_module_owners(self):
        files, patch = convert(reference())
        self.assertNotIn('OLD_MODULES', files['BoardConfig.mk'])
        self.assertNotIn('PREBUILT_PATH', files['BoardConfig.mk'])
        self.assertIn(f'include {HANDOFF_PATH}/BoardConfig.mk', files['BoardConfig.mk'])
        self.assertIn('androidboot.load_modules_parallel=false', files['BoardConfig.mk'])
        self.assertIn('BOARD_INIT_BOOT_IMAGE_PARTITION_SIZE := 8388608', files['BoardConfig.mk'])
        self.assertIn('--- a/BoardConfig.mk', patch)

    def test_preserves_existing_service_owners(self):
        files, _ = convert(reference())
        self.assertNotIn('vendor/bin/vendor_modprobe.sh', files['proprietary-files.txt'])
        self.assertNotIn('vendor/bin/system_dlkm_modprobe.sh', files['proprietary-files.txt'])
        self.assertIn('vendor/etc/init/hw/init.qti.kernel.rc', files['proprietary-files.txt'])
        self.assertIn('vendor/etc/init/hw/init.qti.kernel.target.rc', files['proprietary-files.txt'])
        self.assertIn('existing_service', files['device.mk'])
        self.assertIn('rootdir/etc/fstab.annibale-oss:', files['device.mk'])
        self.assertIn('src: "etc/fstab.annibale-oss"', files['rootdir/Android.bp'])
        self.assertNotIn('rootdir/etc/fstab.qcom', files)

    def test_changed_or_duplicate_loader_owner_is_rejected(self):
        for transform in (lambda text: text.replace('vendor/bin/vendor_modprobe.sh\n', ''),
                          lambda text: text + 'vendor/bin/vendor_modprobe.sh\n'):
            files = reference()
            files['proprietary-files.txt'] = transform(files['proprietary-files.txt'])
            with self.assertRaisesRegex(ValueError, 'owner'):
                convert(files)

    def test_missing_or_duplicate_parallel_setting_is_rejected(self):
        for setting in ('', 'androidboot.load_modules_parallel=true\nandroidboot.load_modules_parallel=true'):
            files = reference()
            files['BoardConfig.mk'] = files['BoardConfig.mk'].replace('androidboot.load_modules_parallel=true', setting)
            with self.assertRaisesRegex(ValueError, 'bootconfig'):
                convert(files)

    def test_platform_policy_include_matches_caf_install_path(self):
        files, _ = convert(reference())
        self.assertIn('include device/qcom/sepolicy_vndr/sm8750/SEPolicy.mk', files['BoardConfig.mk'])
        for value in ('', 'include device/qcom/sepolicy_vndr/SEPolicy.mk\ninclude device/qcom/sepolicy_vndr/SEPolicy.mk'):
            files = reference()
            files['BoardConfig.mk'] = files['BoardConfig.mk'].replace('include device/qcom/sepolicy_vndr/SEPolicy.mk', value)
            with self.assertRaisesRegex(ValueError, 'policy include owner'):
                convert(files)

    def test_already_converted_input_is_rejected(self):
        files, _ = convert(reference())
        with self.assertRaises(ValueError):
            convert(files)


if __name__ == '__main__':
    unittest.main()
