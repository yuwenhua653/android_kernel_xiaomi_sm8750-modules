# R24: native early-module ramdisk integration

R24 packages the verified early subset of the R23 source stages into real
newc/legacy-LZ4 vendor ramdisk fragments, and advances the companion DT repo to
single complete overlays in DTBO containers. It does not add or rebuild C
drivers and does not produce a final vendor_boot or a flash package.

## Original OS4.0.6.0 layout and the new ordering gap

The actual pinned vendor_boot is v4, page size 4096, with one nonempty type-1
platform fragment. Its 108-byte table entry covers all 36,265,107 compressed
ramdisk bytes. The archive has 442 entries, including 432 module files and a
150-root normal modules.load; it also contains a distinct recovery load list.
Those inventories are not a requirement to load all 432 or to blindly add the
remaining OEM normal roots absent from the 66-module native early subset. Several OEM
entries belong to other SoCs or optional/private functionality.

The original bootconfig sets `androidboot.load_modules_parallel=true`.
The reviewed LineageOS first-stage init selects parallel loading from that
setting before the later system/vendor loader scripts run. The R17 scripts
alone therefore cannot enforce early board-dependency insertion order.
The source-native candidate emits `androidboot.load_modules_parallel=false`,
changing only that key in the reviewed flat baseline bootconfig. Duplicate keys,
unknown modes, missing expected settings and a conflicting kernel-command-line
setting are rejected. This governs insertion order; it does not prove successful
probe or satisfaction of every runtime supplier.

The output is an offline native candidate. Do not append `false` after an
existing `true` owner, change the running HyperOS bootconfig, or copy every
other baseline setting into a native ROM without reviewing its ownership.
The separate retained-stock HyperOS path remains unchanged.

## Fragment construction

```sh
python3 -B tools/prepare_annibale_ramdisk_fragment.py \
  --stage /path/to/r23-native-tfa-stage \
  --policy Documentation/xiaomi/annibale-wireless-tfa-partitions.json \
  --stock-vendor-boot /path/to/verified-os406-vendor_boot.img \
  --mkbootfs /path/to/mkbootfs --lz4 /path/to/lz4 \
  --output /path/to/new-native-ramdisk-fragment
```

Repeat with the separate SIA stage/policy when qualifying that family. The
source policy hash, stage result and installed-file manifest must match.
The fragment uses the stage's `vendor_boot` subtree as its archive root, so
modules land at **lib/modules**, not vendor_boot/lib/modules. Only the selected
66 source modules and four text indexes are allowed. All file bytes, owners,
modes and load-list entries are checked after mkbootfs; legacy LZ4 decompression
must reproduce the exact newc archive. The early fragment is the same subset
for both amp choices, although later DLKM contents differ.

Output `vendor_dlkm_fragment.cpio` / `.lz4` denotes a **vendor ramdisk DLKM
fragment (type 3)**, not a vendor_dlkm filesystem image. It contains no fstab,
init, recovery list, proprietary firmware or OEM module. The original platform
ramdisk is inspected in memory only and is never merged with this fragment.
The parser does not extract archive paths and rejects duplicates, traversal,
symlinks/hardlinked regular files, truncated extents and concatenated payloads.

A future full native vendor_boot must provide a separately reviewed platform
ramdisk/fstab and give every fragment a nonzero size, correct offset and type.
It must preserve the selected matching DTB payload and use the corresponding
single-overlay DTBO profile. An archive fragment by itself cannot boot.
The original nonempty table was verified again; the zero-table bug from another
device project is not an observed fault on this stock Annibale image.

## Validation and next boundary

Both real TFA/SIA fragments passed byte/mode/owner and compression roundtrip
checks. The prior kernel and 502 module outputs remain R22-built inputs;
this round's new compilation is DT source, not a new kernel build.
The 116 module-tool tests include malformed ramdisk table/archive/bootconfig
cases. The DT tools pass 15 tests plus the real 32-case single-overlay matrix.
Exact hashes and retained results are in `annibale-r24-validation.json`.

Still open: complete source module coverage; native platform ramdisk/fstab and
ROM device-tree ownership; final vendor_boot/DLKM/init_boot/AVB/recovery assembly;
physical amplifier selection; actual firmware/HAL operation and first OSS boot.
This round neither publishes proprietary partitions to GitHub nor flashes a
phone. GKI signing/CFI and the empty experimental unprotected-symbol list remain
unqualified. Working OEM Wi-Fi/audio/BT/vibration is not an OSS runtime result.

References:

- [LineageOS first-stage init, pinned 65d661b](https://github.com/LineageOS/android_system_core/blob/65d661b1a536701e8b118be4e9728d7b5ca727c9/init/first_stage_init.cpp)
- [AOSP vendor_boot v4 structure, pinned b571449](https://android.googlesource.com/platform/system/tools/mkbootimg/+/b57144927009b2edc925f8ccb133d20a74a6e5d6/include/bootimg/bootimg.h)
- [Native DT containers](https://github.com/yuwenhua653/android_kernel_xiaomi_sm8750-devicetrees/blob/annibale/docs/annibale-dt-images.md)
