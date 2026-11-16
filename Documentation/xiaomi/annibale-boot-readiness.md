# Annibale first-boot qualification — R21

Target: Redmi K90 **annibale / SM8750**, Linux 6.6.144. This is not K90 Pro
Max, myron, or SM8850. R21 prepares boot evidence and an offline candidate;
it does not qualify an image for flashing or change any driver source.

## Two separate candidates

The first diagnostic candidate replaces only `boot`'s kernel and retains the
exact OEM init_boot, vendor_boot, DTBO, recovery and both DLKM partitions.
It isolates whether the current kernel can run with the original drivers.
**It does not exercise the R19/R20 source display/touch changes.**

The native ROM source candidate remains the R20 TFA/SIA module staging and R19
DT compositions. Its boot/ramdisk integration, complete firmware/HAL ownership,
camera and remaining vendor services are not qualified by the stock audit.
No stock-only workaround has been applied to the shared source driver paths.

## Reviewed original layout

The extracted OS4.0.6.0.XPKCNXM partition hashes match its payload manifest;
the payload signature and whole OTA signature have **not** been verified.

| Partition | Observed contents |
| --- | --- |
| boot | v4, uncompressed ARM64 kernel, zero ramdisk and boot_signature |
| init_boot | v4, 2,588,339-byte generic ramdisk |
| vendor_boot | v4, 4,113,008-byte DTB and 36,265,107-byte vendor ramdisk |
| vendor ramdisk table | one 108-byte entry, type 1, offset 0, correct nonzero size |
| bootconfig | parallel module loading enabled; qcom hardware |

The vendor ramdisk table is valid; the empty-table problem observed in another
device project does not apply here. Preserve this layout.

`prepare_annibale_boot_candidate.py` pins both original boot and compiled Image
SHA256, rejects non-kernel-only v4 layouts, copies the original header page
with only kernel_size changed, and writes the new kernel with page padding.
The original OEM AVB footer and signature are deliberately absent: a signature
over the original kernel cannot authenticate the replacement. The tool does
not alter vbmeta, disable AVB, assume fastboot-boot support, or access a phone.
Independent AOSP unpacking reproduced the compiled Image byte-for-byte.

## Retained normal-boot module selection

The original all-partition inventory is unchanged: 637 distinct binaries and
eight names with variants. Recovery contains six alternate audio binaries.
The normal-boot profile excludes recovery and extraction helper `flatten`
copies, then selects 629 names from the actual normal partitions.

zsmalloc and zram have different copies in vendor_boot and system_dlkm.
Both are listed in vendor_boot's normal modules.load. Selection of the early
copies is **conditional on their successful first-stage load**; both physical
copies remain, and their behavior after an early failure is unqualified.
The Android reference libmodprobe treats EEXIST as success, but that is not
proof of the exact OEM loader's runtime behavior.

The selected providers have zero detected import CRC, vermagic flag, missing
hard dependency, duplicate built-in export or selected export collisions.
The 150 early roots have a 150-module hard dependency closure available in
vendor_boot; no later partition is required by that closure. This is a static
availability check, not a claim that all 629 modules are loaded or probed.
Soft dependencies, module options and runtime load/probe order remain open.

## Gates before a first flash

1. **Actual device and firmware:** collect selected read-only properties. Do
   not infer the running Android release from the OTA filename: the reviewed
   boot AVB properties and other extracted metadata describe different versions.
2. **Actual /data filesystem:** original fstab offers F2FS and MIFS. Current
   kernel enables F2FS; MIFS support has not been established. An observed MIFS
   /data is a stop condition for this candidate. Fstab alone is not evidence of
   the filesystem in use; missing permission is unknown, not a pass.
3. **Module security/runtime ABI:** MODVERSIONS matches are necessary but do not
   establish signature trust or CFI compatibility. MODULE_SIG_PROTECT is enabled,
   MODULE_SIG_FORCE is not; the built kernel's unprotected-symbol array is empty.
   Its source therefore bypasses GKI symbol-list restrictions in that case.
   Unknown-key signatures can be tolerated in this configuration, whereas
   malformed/failed signatures can still be fatal. No general claim that every
   stock signature is accepted is made, and this is not production GKI approval.
4. **Installation and restoration:** establish live slot, unlock/AVB policy,
   partition identity, matching original images and a working recovery route.
   Properties alone do not establish acceptance of an unsigned candidate.
5. **First-run evidence:** require kernel/module and mount logs when permitted,
   then separately assess actual hardware. Do not infer driver success from
   `vendor.all.modules.ready`: the OEM script can set it despite module failures.

## Read-only capture

The capture bundle includes `capture_annibale_boot_readiness.cmd` and Python
script. It uses system PATH adb, needs Python 3.8+, and accepts exactly one
authorized ADB device. No root, reboot, flash, unlock, phone writes or app
data collection is performed. Output is a local ZIP containing readiness.json.
Only selected properties, selected mount points, module names and limited
hardware names are retained; transport serials and module addresses are removed.
Unavailable or permission-denied queries remain explicit. Panel sysfs paths are
best-effort and may not identify every panel; no serial-number node is read.

Windows: extract the bundle, connect the running original OS with USB debugging
authorized, and double-click the CMD file. Send the resulting ZIP in `results`.
Linux/macOS: `python3 capture_annibale_boot_readiness.py`.
An optional `--adb` argument accepts an explicit executable path.

R21 validation: 97 host tests passed, actual selected stock ELF audit passed
conditionally, and independent candidate unpack/kernel comparison passed.
Windows execution and real-device capture have not yet been tested. Driver
builds and DT composition were not rerun because those inputs are unchanged;
their R20/R19 records remain prior evidence, not new R21 build results.
