# R29: generated vendor owners and native runtime prerequisites

The R28 handoff supplied source loaders but only removed their extraction-list
entries in the device tree. An already generated vendor tree can still own the
same installed paths, even when its Soong module names differ. The reviewed
vendor metadata uses `system_dlkm_modprobe` / `vendor_modprobe`, while the source
modules use names ending in `.sh`. Both pairs install the same two files.

`prepare_annibale_vendor.py` removes exactly those two `sh_binary` definitions
and their `PRODUCT_PACKAGES` entries. It retains init services, proprietary
libraries, firmware, BoardConfigVendor and all unrelated owners. It writes a
patch and before/after hashes into a new directory, leaving its input unchanged.
Unexpected sources, destinations, duplicate owners, dynamic properties or package
layouts stop conversion for review.

The prepared example patch targets
`soytony/proprietary_vendor_xiaomi_annibale@1e1509837ee796de4fd85719bfc66896f8bb06fc`.
That reference is **not automatically an OS4.0.6-matched vendor tree**. Its
metadata patch proves removal of the reviewed collision, not binary/HAL ABI.
On another regenerated tree, run the tool against its explicit reviewed HEAD;
do not force-apply the example patch across a mismatch.

## Runtime packages and wiring

The handoff now explicitly selects all providers used by its loaders:

| Package | Required installed programs |
| --- | --- |
| sh_vendor | /vendor/bin/sh |
| toolbox_vendor | /vendor/bin/modprobe, /vendor/bin/setprop |
| toybox_vendor | /vendor/bin/uname, /vendor/bin/tr |

`check_annibale_vendor_runtime.py` checks the source-text contract: unique
`gki.modprobe` and `vendor.modprobe` services, reviewed credentials/SELinux domain,
serial early-init start order, and the normal post-fs-data ready barrier. The
existing charger barrier is recorded separately and remains unqualified. No
new service, permissive domain, ready-property shortcut or forced HAL start is
introduced.

It also follows the reviewed init imports and checks the ueventd firmware search
file. The fstab validator now requires the existing read-only, slot-selected
modem, modemfirmware, DSP and Bluetooth mounts. Their actual fstab entries are
unchanged. A path check does not prove that a requested firmware file exists or
that signed firmware is compatible with the source driver.

## Reproduce the generated metadata conversion

```sh
python3 -B sm8750-modules/tools/prepare_annibale_vendor.py \
  --vendor /path/to/reviewed/vendor/xiaomi/annibale \
  --expected-commit YOUR_REVIEWED_COMMIT \
  --output out/annibale-vendor-conversion

# First review validation.json and the patch against the named vendor tree.
git -C /path/to/reviewed/vendor/xiaomi/annibale apply --check \
  /absolute/path/out/annibale-vendor-conversion/annibale-vendor-conversion.patch
git -C /path/to/reviewed/vendor/xiaomi/annibale apply \
  /absolute/path/out/annibale-vendor-conversion/annibale-vendor-conversion.patch
```

The complementary device patch still removes the two extraction-list entries,
so a later regeneration should not reintroduce the conflicting owners. Install
one newly generated handoff family at `device/xiaomi/annibale-oss-kernel`, then
apply its device patch to the pinned reference tree. Do not combine both audio
families. If already using R28, update the handoff Product.mk runtime package
selection; the device conversion patch itself is unchanged.

After applying both metadata conversions, run:

```sh
python3 -B sm8750-modules/tools/check_annibale_vendor_runtime.py \
  --vendor /path/to/vendor/xiaomi/annibale \
  --rom /path/to/device/xiaomi/annibale \
  --handoff /path/to/device/xiaomi/annibale-oss-kernel \
  --report out/annibale-vendor-runtime.json
```

This does not replace Android init parsing, full Soong/Kati/SELinux compilation,
complete firmware/HAL qualification or a final installed-image audit. The full
vendor+odm set and Android 17 native integration still need qualification.
Kernel/module binaries are reused from R28; no fresh kernel build or phone flash
is claimed. **The handoff is not a flash package.**

## R29 observed results

- Metadata conversion applied cleanly to an isolated copy; before/after hashes
  matched. Both old script packages disappeared and both source packages plus
  the three runtime providers were selected once (1696 total package entries).
- Both complete reference BoardConfig files evaluated with GNU Make after
  supplying the actual generated reference BoardConfigVendor.mk. It was not
  replaced with an invented stub. Optional Lineage/camera includes and full
  Android sources were absent; this remains a partial evaluation.
- 96 reference init files passed the scoped runtime check. Both handoffs retain
  217/218 modules. All 180 tests passed.
- The user's OS4.0.6 OTA vendor, modem and modemfirmware partitions were actually
  reconstructed, operation-hash checked and whole-partition-hash checked.
  EROFS vendor extraction exited successfully; host timestamp-setting warnings
  on dangling symlinks do not constitute a rebuilt vendor image. OTA signature
  verification was not performed.
- OTA vendor reports Android 15 / SDK 35 / OS4.0.6.0.XPKCN. This describes the
  vendor partition, not the Android 17 system partition or a failed update.
- Its two module services, credentials, start order and readiness barriers match
  the scoped source contract. The target-ready rc is byte-identical to the
  reference; the main kernel rc differs. Do not overwrite the complete OEM rc
  merely because the selected service contract matches.
- The four gen8 GPU firmware files were inventoried with byte hashes. No
  spss1d/t/p MDT files were found in the two FAT firmware partitions, and the
  vendor firmware directory has no such files. The OTA also contains a small
  separate spuservice partition, which was hash-checked. Its relationship to
  SPSS reload is not established. The kernel supports attaching a processor
  already started by UEFI; actual fuse state, attach and firmware reload remain
  unverified. No firmware was fabricated or renamed to fill this gap.

See `annibale-r29-validation.json` for hashes and qualification boundaries.
