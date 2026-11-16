Latest: [R16 microphone enable, smartpa ABI and family-specific loading](annibale-audio-runtime.md).

Latest: [R15 opt-in smartpa source integration](annibale-audio.md).

Latest: [R14 native load dependencies and partition staging](annibale-load-integration.md).

Latest: [R13 WLAN and IPA/RMNET integration](annibale-network.md).

Latest source build expansion: [R12 platform modules](annibale-platform.md).

# R11: HyperOS 4 and native ROM qualification

The target is the user's **OS4.0.6.0.XPKCNXM**, Redmi K90 / annibale / SM8750.
The supplied official OTA has Android 17 / SDK 37 / October 2026 security patch
metadata. Its embedded incremental is `17OS4.0.261026.215942994.QCPECN.S`.
The kernel remains **6.6.118-android15-8**, with 4K pages, MODVERSIONS, CFI and
module BTF. Android 17 userspace does not by itself require moving this device
to a 6.12 kernel. Exact evidence is in `annibale-r11-validation.json`.

This round changes verification tools and records; it does not change kernel
or driver source. R10's complete outputs were rechecked, including their input
hashes. **Neither HyperOS nor a native ROM has been boot-qualified.**

## Two independently required paths

| Path | R11 evidence | Integration rule |
| --- | --- | --- |
| Native ROM source build | 411 kernel + 58 selected external modules pass fresh ARM64, CRC, vermagic, dependency and BTF checks | Continue using source Kbuild/modpost and the same kernel output; retain LOS interfaces and require explicit module ownership for any retained blobs |
| HyperOS retained modules | 1,015 files, 637 distinct binaries, 629 names; 29,475 built-in-import and 4,929 retained-provider CRC checks, zero detected ABI blockers | Use the exact OS4 firmware inventory and its partition-specific module policy; do not replace its entire stack with the qualification module set |
| Combined gate | `incomplete_inventory` | A pass on one path cannot mask a failure or unresolved inventory on the other |

The native build used the experimental `qualify` profile, including the P11
fingerprint candidate and read-only MCA battery bridge. This is compilation
qualification, not a deployable native ROM configuration. The standard board
profile still leaves experimental MCA disabled. The measurement-only bridge
must not replace HyperOS's charging policy stack or be enabled beside it.

The selected 58 external outputs do not yet cover the entire native ROM.
GPU, WLAN/Bluetooth, video, networking/data, Xiaomi display/camera interfaces,
amplifier selection and full charging policy still need integration. The report
lists 170 stock module names without an identically named built source output.
This is a planning inventory, **not 170 confirmed mandatory missing drivers**:
stock includes optional tests and other-board variants, and source alternatives
can have different names. A matching module name is likewise not evidence of
matching ioctls, sysfs, firmware protocols, HALs or hardware behavior.

## Keep module owners and boot modes explicit

There are 459 names shared between the current source output and stock inventory.
Never concatenate both module lists into one ROM. Each ROM's partition manifest
must choose one provider per name and recheck the resulting dependency closure.
The modules repository's `annibale-r11-ownership.json` records these overlaps.

Six audio modules have distinct recovery and normal vendor_dlkm binaries:
`adsp_loader_dlkm`, `gpr_dlkm`, `q6_notifier_dlkm`, `q6_pdr_dlkm`,
`snd_event_dlkm`, and `spf_core_dlkm`. These are separate boot-mode candidates,
not six broken normal-boot modules. Do not let recovery copies satisfy normal
boot dependencies during final package validation.

`zram` and `zsmalloc` also have different vendor_boot and system_dlkm binaries.
Vendor_boot's normal `modules.load` lists them at lines 84 and 12 respectively;
system_dlkm carries its own list. Preserve the early loader context and prove
which providers are selected before consolidating or replacing these files.
The all-inventory audit intentionally leaves all eight ambiguities unresolved.

## Observed startup layout

The OTA uses boot/init_boot/vendor_boot header v4. Boot holds a 36,801,024-byte
Image and no ramdisk; init_boot carries the generic ramdisk. Vendor_boot has a
valid 108-byte table with one PLATFORM fragment (type 1, offset 0, size
36,265,107), a 4,113,008-byte DTB area and 204 bytes of bootconfig. A repacker
must preserve the table and its fragment semantics; a zeroed table is invalid.
Vendor and system DLKM images are EROFS with LZ4_0PADDING. The stock fstab includes
first-stage mounts for both. It also lists f2fs and mifs alternatives for /data;
the active device filesystem and encryption behavior are not yet observed.

For HyperOS, the stock DTB/DTBO, init_boot, vendor ramdisk and matching firmware
remain the comparison baseline. For a native ROM, build the source DTB/DTBO and
assemble ramdisks/module partitions through its device tree; blindly copying a
HyperOS ramdisk or init configuration is not native ROM adaptation.

## Reproduce the combined check

Run from the modules repository after the complete kernel and selected external
module builds documented in `annibale-full-build.md`:

```sh
python3 -B tools/check_annibale_rom_paths.py \
  --kernel-out /path/to/out/annibale-btf \
  --module-stage /path/to/out/annibale-external/modules-XXXXX \
  --stock-modules /path/to/extracted-os4-partitions \
  --report /path/to/dual-rom-check.json
```

Keep stock partitions in separate subdirectories and retain `modules.load*`.
The source stage must include the successful build helper's `build.json` at its
original paths. All seven recorded kernel inputs (including Image, vmlinux,
configuration and symvers) must match. A missing/stale record blocks the source
path. Both checks run even if one fails. Exit 0 means only `static_checks_passed`;
blocked or unresolved inventories exit 1 with a report. The tool is read-only,
does not install modules, and never labels a static result boot-compatible.

## Remaining qualification

The R10 build has CONFIG_MODULE_SIG_PROTECT enabled but an empty generated
`gki_unprotected_symbols` list. The kernel implementation treats that case as
no GKI allowlist enforcement. This qualification build therefore does not prove
production allowlist compatibility. R11 adds no signature/CRC/CFI bypass.
Signature trailers on 96 stock binaries do not establish trust with the target
kernel. Final KMI policy, signatures, runtime CFI/BTF, selected load order,
DT selection and both ROMs' hardware/HAL behavior remain unverified.

The OTA was read with HTTP ranges pinned by ETag. Payload metadata, each selected
operation and all nine reconstructed partition hashes matched the OTA metadata.
This is not verification of the OTA cryptographic signature, whole ZIP/payload
hash, or AVB trust. Detailed reports are retained separately; no proprietary
module binaries or firmware images are committed to these source repositories.
