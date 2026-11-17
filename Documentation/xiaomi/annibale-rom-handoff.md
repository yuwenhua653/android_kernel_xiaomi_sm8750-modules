# R26: Annibale source-built kernel handoff to a native ROM tree

R26 prepares a pinned conversion patch for the third-party
[xiaomi-annibale tree at 1ed1ecc](https://github.com/xiaomi-annibale/android_device_xiaomi_annibale/tree/1ed1eccfa3f68e1ec440b7f5e87ac97dc89475fe).
This is a handoff of separately built source outputs to Android image assembly,
**not an in-ROM kernel compilation hook or a complete ROM build**. The reference
is lineage-23.2 with an older 6.6.77 prebuilt baseline; it does not establish
Android 17 / OS4.0.6.0 firmware/HAL compatibility. HyperOS retained-stock
ownership and the kernel/DT source baselines remain unchanged.

## Actual changes

The patch replaces the reference prebuilt kernel/DT/module section with one
handoff include. Image, ordered DTBs, native DTBO and 200 TFA / 201 SIA modules
are bound to R23/R25 reports. Old version-directory/flatten system_dlkm copies
and stock blocklist owners are removed. Standard BOARD_*_KERNEL_MODULES variables
consume the flat lists. The 66 early modules use a separate type-3 DLKM fragment
with KERNEL_MODULE_DIRS `top`; bootconfig selects sequential first-stage loading.

Two source sh_binary modules replace the proprietary loader script entries.
The existing init.qti.kernel.rc and init.qti.kernel.target.rc owners remain;
no duplicate services, new properties or SELinux domains are introduced.
The handoff includes toolbox_vendor, which supplies modprobe and setprop.
Actual vendor shell, uname/tr, service graph and enforcing policy still need
checking. Regenerate the vendor tree: deleting entries from proprietary-files
alone cannot remove stale Android.bp or copy owners in an already generated tree.

Before insertion, the loader now rejects missing, broken, copied-directory or
misdirected /system/lib/modules and /vendor/lib/modules aliases. It reads lists
from DLKM mounts, but Android modules.dep references these aliases. Resolution
uses shell builtins. Serial insertion, early-provider checks and failure handling
remain. This is not a check of mount identity or successful asynchronous probes.

A separate fstab.annibale-oss source feeds vendor/etc/fstab.qcom and the
first-stage ramdisk. The original recovery fstab stays byte-identical.
Recovery/charger lists and runtime behavior are not qualified by this conversion.

The handoff includes 1003 UAPI headers from the matching ARM64 `headers` target.
An export-only Makefile implements the reference tree's headers_install interface;
it does not build a kernel. The initial kernel headers_install attempt failed
at missing host rsync after generation; the successful headers target and explicit
export were used instead. All exported headers are byte-checked, including asm
wrappers. A freestanding ARM64 syntax check covers types/ioctl/DMA-heap/MSM-DRM;
libc-dependent input/audio/video headers were not checked without an Android sysroot.

## init_boot and reproduction

The original 8 MiB init_boot declaration and v4 arguments remain. The handoff
sets PRODUCT_BUILD_INIT_BOOT_IMAGE=true and rejects a prebuilt init_boot owner.
Evaluating pinned Android board_config logic selects a native generic-ramdisk
build. **No init_boot was compiled.** The OEM generic ramdisk was inspected only;
no OEM init binary is copied. Generic first-stage init must come from the native
platform. The reviewed init supports flat /lib/modules and sequential loading.

Use clean reference commit 1ed1ecc, verified R22 output, R23 family stage and
R25 native-display images. The helper rejects another/dirty reference, mismatched
hashes/families, existing outputs and input overlap. It emits a patch without
applying it or modifying a live ROM checkout.

```sh
# Use the R22 compiler/tool environment.
make -C sm8750 O="$PWD/out/annibale-btf-r22" ARCH=arm64 LLVM=1 headers
family=tfa # repeat separately with sia
python3 -B sm8750-modules/tools/prepare_annibale_rom_handoff.py \
  --kernel-out out/annibale-btf-r22 \
  --stage out/annibale-r23-android-final-$family \
  --native-images out/annibale-r25-native-verified-$family \
  --rom-reference reference-annibale-rom \
  --output out/new-native-handoff-$family
```

For an isolated integration checkout, review/apply the emitted patch to the
pinned device tree and put one family's handoff at
`device/xiaomi/annibale-oss-kernel`. Regenerate proprietary build files and check
for conflicting script owners before an Android build. Do not install both
families; actual amplifier identity remains unknown.

## Evidence and boundary

141 tool tests passed, including 8 new methods. The real patch passed apply
--check, application in an isolated checkout and diff --check. Generated Make
includes evaluated for both families using actual patched bootconfig values:
66+1+133 / 66+1+134 modules. Reintroduced stock module/init_boot owners fail.
All 1003 headers export unchanged; modules match R23 bytes and DTB order is intact.

This is GNU Make evaluation, not Kati/Soong or SELinux compilation. Full
BoardConfig evaluation stopped at missing vendor/xiaomi/annibale/BoardConfigVendor.mk;
no empty substitute was supplied. Third-party vendor init files show the expected
services/domain but are not the user's exact OS4 baseline; they were not copied.
Pinned Qualcomm policy labels the loader paths/ready property and allows system
DLKM loading; that inspection is not a full enforcing-policy proof.

Remaining: regenerate matching vendor owners, complete driver/firmware/HAL
coverage, compile native init_boot and ROM images, inspect final aliases/service
graph, qualify enforcing policy, recovery/charger and hardware. Reference AVB
flags/test keys and partition sizes are retained for review, not device-qualified.
Its 24 MiB DTBO declaration differs from the 18 MiB OTA image length; image length
alone does not establish physical capacity. **Not a flash package.** No kernel
or module C rebuild, CI build, flashing or phone test occurred.

References:

* [Qualcomm policy](https://github.com/LineageOS/android_device_qcom_sepolicy_vndr/tree/490d47fb8438a2ecd99c1338472f80561572c362)
* [First-stage init](https://github.com/LineageOS/android_system_core/blob/65d661b1a536701e8b118be4e9728d7b5ca727c9/init/first_stage_init.cpp)
* [Android init_boot selection](https://github.com/LineageOS/android_build/blob/90d006387398ae6899145e6531a304500cfa0f70/core/board_config.mk)
* [Android module-fragment rules](https://github.com/LineageOS/android_build/blob/90d006387398ae6899145e6531a304500cfa0f70/core/Makefile)
* [Third-party service reference](https://github.com/soytony/proprietary_vendor_xiaomi_annibale/tree/1e1509837ee796de4fd85719bfc66896f8bb06fc/proprietary/vendor/etc/init/hw)
