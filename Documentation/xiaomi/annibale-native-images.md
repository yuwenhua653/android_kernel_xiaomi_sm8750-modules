# R25: offline native image assembly

R25 produces actual boot, vendor_boot, DTBO, system_dlkm and vendor_dlkm
containers for the R23 partial source-native selection. Both TFA (200 modules)
and SIA (201 modules) pass independent unpack/extraction checks. This closes
an image-assembly gap, not the full native ROM or first-boot gap. No C drivers
were added or rebuilt; the kernel and module binaries remain the R22 inputs.

## Ownership and contents

The retained-stock HyperOS path is unchanged. These images must not be combined
with the original HyperOS module-loading services or stock DLKM partitions.
There is no discovered complete Annibale ROM device tree in the three kernel
repositories, so this round does not claim that a ROM build consumes them.

* boot: the qualified R22 Image in a kernel-only v4 header derived from the
  hash-pinned original. The original header has an empty command line and zero
  OS-version/security-patch fields. Original AVB metadata/footer is not copied.
* vendor_boot: new platform fragment (type 1) plus the 66-module early fragment
  (type 3), with explicit nonzero table sizes and contiguous offsets. The new
  platform fragment contains only first_stage_ramdisk/fstab.qcom. Source DTBs,
  sequential-load bootconfig and the original hardware load addresses are used.
  OEM fingerprint command-line tokens are omitted. There is no recovery ramdisk.
* DTBO: the R24 native display profile matching the selected amplifier, with
  complete revision-specific overlays. dtb.img is also emitted for inspection.
* system_dlkm: rfkill plus the generated module indexes.
* vendor_dlkm: the remaining 133 TFA or 134 SIA modules and their indexes.

The fstab candidate keeps the reviewed logical partitions, AVB chain names,
F2FS metadata/data and wrapped-key encryption settings. It excludes MIFS and
HyperOS-specific overlay mounts, and selects EROFS for both DLKM partitions.
Optional GSI public-key paths were removed because no corresponding keys are
provided. Retaining AVB settings does not supply matching vbmeta/signatures.
The source-native platform contains no firmware, HALs, generic init or copied
OEM module. A complete native ROM must supply and qualify those owners.

## Filesystem checks

EROFS uses 4 KiB blocks, LZ4HC and zero-padding incompatibility bit 1. This
kernel enables CONFIG_EROFS_FS_ZIP and CONFIG_LZ4_DECOMPRESS; it does not have
a CONFIG_EROFS_FS_ZIP_LZ4 symbol. Every inode is inspected for root ownership,
0755 directories/0644 files and its SELinux xattr. system_dlkm uses
system_dlkm_file; vendor_dlkm uses vendor_file, following the pinned AOSP policy.
This is label validation, not proof that the final ROM enforcing policy allows
module loading. The constrained reader rejects unsupported/shared-xattr layouts.
fsck.erofs independently extracts compressed file data; file sets and all bytes
must equal the verified source stage. AOSP unpack_bootimg independently checks
the kernel, DTB, bootconfig and both compressed ramdisk fragments.

The tool binds the kernel config/Image/release/Module.symvers, stage manifest,
fragment and DT reports before assembly. It rejects existing output directories.
It performs no device access, AVB signing, partition resizing or flashing.

## Reproduce

Use the matching R22 kernel, R23 stage, R24 fragment and DT outputs. Run from
the directory containing the three repositories and tools; use a new output
path for each invocation. The standalone AOSP tools are from mkbootimg commit
b57144927009b2edc925f8ccb133d20a74a6e5d6; tool hashes are in the result report.
The stock images are private, hash-pinned OS4.0.6.0 reference inputs, not source
outputs. Extracted OTA partition hashes were checked; OTA signatures were not.

```sh
family=tfa # repeat separately with sia
python3 -B sm8750-modules/tools/build_annibale_native_images.py \
  --kernel-out out/annibale-btf-r22 \
  --stage out/annibale-r23-android-final-$family \
  --fragment out/annibale-r24-ramdisk-final-$family \
  --dt-images out/annibale-r24-dt-images --devicetrees sm8750-devicetrees \
  --stock-boot out/annibale-r25-reference/boot.img \
  --stock-vendor-boot out/annibale-r23-reference/vendor_boot.img \
  --mkbootimg out/annibale-r25-reference/mkbootimg.py \
  --unpack-bootimg out/annibale-r25-reference/unpack_bootimg.py \
  --mkfs-erofs tools/kernel-build-tools/linux-x86/bin/mkfs.erofs \
  --fsck-erofs tools/kernel-build-tools/linux-x86/bin/fsck.erofs \
  --mkbootfs tools/kernel-build-tools/linux-x86/bin/mkbootfs \
  --lz4 tools/kernel-build-tools/linux-x86/bin/lz4 \
  --display-mode native --output out/new-r25-$family
ANNIBALE_TEST_EROFS="$PWD/out/new-r25-tfa/vendor_dlkm.img" \
  python3 -B -m unittest discover -s sm8750-modules/tools/tests
```

All 133 module-tool tests passed, including 17 new test methods. Real-image
mutations reject incorrect labels/modes/owners, unsupported features, truncated
images and metadata outside the image. Stage mutations reject missing, changed,
extra and symlinked files. Fstab tests cover mount/AVB/encryption omissions.
Image builds succeeded for both families; kernel/DT source compilation was not
repeated. Exact image sizes and hashes are in annibale-r25-validation.json.

## Remaining gates

These are **unsigned, partial, offline candidates**, not flash packages. There
is no init_boot, recovery, vbmeta, full super/dynamic-partition layout or flash
script. Next work must connect a complete native ROM device tree, reconcile
module-loader and firmware/HAL owners, complete necessary driver coverage, and
qualify AVB, recovery and actual storage/decryption. Physical amplifier choice
is not yet established. Empty experimental GKI unprotected-symbol policy,
signatures and CFI remain unqualified. No phone boot or functional validation
was performed; healthy stock Wi-Fi/audio/BT/vibration remains OEM evidence.

References:

* [AOSP mkbootimg, pinned b571449](https://android.googlesource.com/platform/system/tools/mkbootimg/+/b57144927009b2edc925f8ccb133d20a74a6e5d6/)
* [AOSP SELinux file contexts, pinned e972e93](https://android.googlesource.com/platform/system/sepolicy/+/e972e936da539085447b54b879214ff4589983b7/private/file_contexts)
* [LineageOS build Makefile, pinned 90d0063](https://github.com/LineageOS/android_build/blob/90d006387398ae6899145e6531a304500cfa0f70/core/Makefile)
* [Matching EROFS kernel format](https://github.com/yuwenhua653/android_kernel_xiaomi_sm8750/blob/c70ed7c690cc908451daf53c14afa8d3ceb20ca9/fs/erofs/erofs_fs.h)
