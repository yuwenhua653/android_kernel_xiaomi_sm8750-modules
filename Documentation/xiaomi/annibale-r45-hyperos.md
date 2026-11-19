# Annibale R45: HyperOS 4.0.6 retained-OEM boot trial

This is a **first temporary-boot candidate**, not a production or flash-qualified
release. No OSS boot of this device has yet been observed. The known working
November 17 capture is the original OS4.0.6.0.XPKCNXM system, not an OSS success.

## Kernel change

The extracted OS4.0.6 boot kernel enables CONFIG_MEMFD_ASHMEM_SHIM, while the
previous source Image lacked this interface. Restore the three unmodified ACK
6.6 shim files and shmem file-operation hooks from commit
759894c87b6e77bb3262bdf703ec474ab323d5ab (android15-6.6-2025-06_r16), and enable
them for annibale. The separate /dev/ashmem implementation remains present.
This preserves ashmem ioctl handling on memfd descriptors, including name/size,
protection masks, pin compatibility, and 32-bit ioctl number translation.

ACK subsequently removed this shim from older kernel branches; its removal
message says it is needed for 6.12 and newer. Restoring it here is a deliberate
match to this device's extracted OEM configuration, not a claim that every 6.6
kernel requires it or that its absence caused the earlier black screen.
Source provenance and file hashes are in the kernel repository's
Documentation/xiaomi/annibale-os406-shmem-source.json.

Published kernel commit: c17ffa89f4fe197dd0e83c36cb517b6c0c13dc34.
Build-local commit: e7af0d4f1111 (preserved on validation/r45-local).
Both have tree 4540277f23746c417d0de314505c2a2ccbc49a72. The existing build carries
the local commit in its release string; no spoofed stock vermagic is used.

## Completed offline evidence

- Image and 411 in-tree modules linked with strict modpost, BTF, and CFI enabled.
- 94 external modules rebuilt against this core, including optional SLA, and
  checked together with the 411 core modules. This verifies the native source
  build remains intact; these modules are **not installed by the HyperOS trial**.
- 629 selected retained-OEM module names: zero detected CRC/provider/vermagic
  blockers; the zram/zsmalloc first-stage ownership conditions still apply.
- No selected namespace or GPL-license conflict. 974 available declared import
  CFI type IDs match their providers; 33,096 imports have no comparable pair.
  This does not check every indirect callback or runtime structure layout.
- 94 PKCS7 trailers passed syntax parsing; 535 modules are unsigned. This is not
  cryptographic signature or trusted-key validation.
- Six missing softdep declarations remain in the unchanged OEM inventory:
  dwc3_msm -> phy_msm_snps_hs; ipam -> subsys_pil_tz/qcom_arm_smmu_mod;
  msm_video -> subsys_pil_tz; pinctrl_kera/tuna -> qcom_tlmm_vm_irqchip.
  AOSP libmodprobe attempts soft dependencies non-strictly. These warnings are
  not converted into fake driver fixes; the exact OEM loader and probe order
  are still runtime checks.
- The GKI unprotected-symbol array is empty in this qualification build. It
  therefore lacks production GKI symbol-list enforcement. Signature trust,
  production KMI policy and GKI certification are not claimed.
- 338 tool/source tests passed without skips, using real EROFS and bpfmt fixtures.
- Android mkbootimg's independent unpacker recovers the exact candidate Image.
  Only boot header kernel_size and kernel payload change; the unsigned candidate
  does not reuse the OEM AVB footer or any OEM signature.

## Test package and stopping conditions

trial_annibale_hyperos.py uses Python 3.8+ and existing adb/fastboot from PATH.
The Windows CMD menu invokes it. Start from the working original OS4.0.6 system.
It verifies exact system/vendor fingerprints, original kernel release, unlocked
orange state, Enforcing SELinux, F2FS, and the current A/B slot. Then it reboots
to bootloader fastboot, checks device/mode/slot/unlock/partition/download sizes,
and issues **one fastboot boot** with the hash-pinned image.

No flash, erase, unlock, set_active, AVB-disabling, or automatic retry command
exists. If the bootloader rejects temporary boot, it stops and must not be
worked around by manually flashing the candidate. Temporary-boot support and
use of the on-device init_boot/vendor_boot by this OEM bootloader are unproven.

The report only calls a completed ADB boot a candidate boot when the release is
6.6.144-4k-ge7af0d4f1111, the exact OS4 system fingerprint matches, and the slot
matches the preflight capture. Returning to the old kernel is not a pass.
It compares loaded module names, but never equates their presence with working
Wi-Fi, audio, Bluetooth, vibration, camera, charging or suspend.

A normal reboot leaves the temporary kernel and loads the existing on-device
images. The return-stock action requests only a normal reboot and records that
restoration has not yet been verified. If USB is unavailable, restart manually
with the hardware Power button; do not wait for capture before recovering.
No stock image is flashed, and no slot switch is suggested.

## Remaining gate

Observe this exact candidate starting HyperOS, then test Wi-Fi, audio, Bluetooth,
vibration and normal restart first. Camera, charging, suspend, thermal behavior
and repeat boots remain required before a daily-use release. A successful
retained-OEM trial is not proof that the source-native driver package works on
HyperOS; native vendor/SELinux/ROM integration remains the R44 track.

References:
- https://android.googlesource.com/kernel/common/+/759894c87b6e77bb3262bdf703ec474ab323d5ab/mm/memfd-ashmem-shim.c
- https://android.googlesource.com/kernel/common/+/aba16327dea522cc30a043a71bb604e5f0e2dc84
- https://android.googlesource.com/platform/system/core/+/refs/heads/main/libmodprobe/libmodprobe.cpp
- https://source.android.com/docs/core/architecture/partitions/generic-boot
