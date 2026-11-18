# R31: OS4 media inputs and stock network evidence

This round corrects twelve OS4 extraction-list discrepancies and checks the
previously unexamined system_ext inputs. It does not add twelve kernel drivers.
The kernel, device tree and R29 handoff binaries are unchanged. There is no new
kernel/Android build, flashable image or hardware qualification in this round.

## Display and video

All ten `sm8750_sr_*.dlc` files from the old vendor list exist in the verified
OS4.0.6.0.XPKCNXM dump under `odm/etc/display/`. The migration changes both the
extraction source and installed destination to that stock location. It does not
create aliases at the old vendor paths. Use the complete matching OS4 blob set;
this is not a shim for an OS3 display HAL.

The Sun video source selects `.fwname = "vpu35_4v"`; the VPU33 selection belongs
to Pineapple. The actual Annibale dump has both VPU35 firmware variants and
neither of the two VPU33 files in the old list. Only those two absent VPU33
extraction entries are removed. VPU35 firmware stays selected and unmodified.

`prepare_annibale_os4_media.py` checks both partition build properties, twelve
exact asset sizes/hashes, absence of the old files, and a pinned Sun platform
source before writing a patch. It rejects existing destination owners, changed
entry flags and missing retained firmware. Inputs are read-only. Comments are
preserved, including comments that contain an old filename.

Starting with the pinned ROM reference at
`1ed1eccfa3f68e1ec440b7f5e87ac97dc89475fe`, apply the R30 base conversion and
OS4 AuthSecret patches first. Then prepare the media patch:

```sh
python3 -B sm8750-modules/tools/prepare_annibale_os4_media.py \
  --dump /path/to/extracted-stock \
  --proprietary-files /path/to/device/xiaomi/annibale/proprietary-files.txt \
  --output out/new-os406-media
```

Review and apply `annibale-os406-media.patch` in the device tree. Regenerate
proprietary build files so the models have ODM install owners; stale generated
vendor owners are not repaired by editing this input list alone. The complete
base + AuthSecret + media patch chain was applied to a clean pinned worktree,
checked with `git diff --check`, and its final list matched the generated list.

## Expanded inventory

The stock vendor_dlkm and system_ext images were reconstructed from the same OTA
payload manifest used in R30. Operation and whole-partition hashes verified,
and EROFS extraction returned success. This is not OTA signature validation.

| Scope | Present | Missing | Outside scope |
| --- | ---: | ---: | ---: |
| R30 vendor + odm, after AuthSecret | 3762 | 30 | 103 |
| R31 vendor + odm, after media migration | 3772 | 18 | 103 |
| R31 vendor + odm + system_ext | 3856 | 24 | 13 |

The final row adds 84 present and six missing system_ext entries. The 13
unselected entries are product (9), system (3), and mi_ext (1). These counts
refer to extraction entries, not hardware features or working drivers.

The audit now accepts an explicit partition scope and requires every selected
partition directory to exist. Default vendor/odm behavior is preserved. It never
assumes an unselected partition is present just because a directory exists.

```sh
python3 -B sm8750-modules/tools/audit_annibale_vendor_blobs.py \
  --dump /path/to/extracted-stock \
  --proprietary-files /path/to/device/xiaomi/annibale/proprietary-files.txt \
  --partitions vendor odm system_ext --report out/os406-inputs.json
```

This audit still returns nonzero for the remaining missing inputs. Their exact
paths and sections are in the R31 validation record. Camera models/libraries,
QESD/QSAP services, the old SLA service entries and six system_ext components
remain unresolved; they have not been silently removed to obtain a passing
result. No same-basename replacements for these missing entries were found in
the extracted system_ext. Literal-reference absence is not proof that an asset
is unnecessary or that a dynamically loaded service is unused.

## RMNET and SLA

`compare_annibale_rmnet.py` compares actual stock and native module parameter
names/types and dependencies. Both TFA and SIA handoffs match stock for
`rmnet_perf`, `rmnet_shs` and `rmnet_offload`. Stock itself does not export
`rmnet_perf_ingress_deag` or `rmnet_perf_opt_mode`, although stock `nicmd.rc`
requests them. Thus these two R30 findings are inherited stock init/metadata
discrepancies, not newly lost OSS exports. No guessed parameter aliases were
added. Requested tuning and unload/reload behavior still require review; the
runtime checker remains blocking and this comparison cannot override it.

```sh
python3 -B sm8750-modules/tools/compare_annibale_rmnet.py \
  --stock-modules /path/to/extracted-stock/vendor_dlkm/lib/modules \
  --handoff /path/to/handoff --report out/rmnet-comparison.json
```

The stock dump really contains `sla.ko`, and selected `slad.rc` requests it.
The native handoff still lacks this module. Neither a substitute nor a stub was
added. Metadata parity of RMNET is not permission to mix stock and OSS modules.
The two missing old SLA service extraction entries also do not justify removing
the AIDL `vendor.qti.sla.service/ISlaAIDLService/default` declaration: that
interface is declared in the current stock manifest too. Its provider and
native userspace contract remain to be resolved separately from the kernel
module gap.

## Validation and next gates

All 219 tests pass, with no skipped EROFS test; the fixture uses the restored R29
TFA modules. Negative tests cover altered firmware/source hashes, wrong builds,
symlinks, changed owners, parameter types, and absent selected partitions.
Real stock metadata comparison passes for both audio families.

Still required: remaining extraction inputs, regenerated vendor/odm owners and
blob fixups, ELF/linker/VINTF/SELinux checks, SLA source integration, RMNET
lifecycle, factory Pronto property handling, SPSS UEFI attach/reload, full ROM
assembly and hardware testing. Display super-resolution, codec/protected
playback and network behavior have not been exercised on a device. HyperOS
retained-stock ownership remains unchanged; this optional migration prepares
the native OS4 input path without changing the default extraction profile.

Evidence: [R31 validation](annibale-r31-validation.json),
[pinned media profile](annibale-os406-media-assets.json),
[previous R30 scope](annibale-vendor-os406.md).
