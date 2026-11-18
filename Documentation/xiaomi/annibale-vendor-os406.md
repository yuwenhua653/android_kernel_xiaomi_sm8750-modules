# R30: OS4 vendor/odm inputs and init module consumers

R30 fixes two concrete extraction problems and expands the native runtime gate.
It does not rebuild the kernel/modules, generate a complete proprietary vendor,
compile Android, change credential behavior or qualify a flash.

## Changes

The pinned device tree `xiaomi-annibale/android_device_xiaomi_annibale` at
`1ed1eccfa3f68e1ec440b7f5e87ac97dc89475fe` lists eight configuration files twice.
The reviewed LineageOS extract-utils `FileTree.add_with_parts` rejects duplicate
destination entries. The handoff converter now removes identical duplicates,
retaining the first occurrence and all comments. Conflicting sources, flags or
generated symlink owners still fail; duplicate loader owners still fail before
deduplication. The eight entries cover display, GNSS and thermal configuration.

The separate OS4 AuthSecret patch updates the extraction inventory to the actual
OS4.0.6 files:

| Old entry | OS4 handling |
| --- | --- |
| odm/etc/vintf/manifest/vendor.xiaomi.hardware.authsecretd.xml | Select vendor.xiaomi.hardware.miauthsecretd.xml in the same directory |
| odm/lib64/libmi_authsecretd.so | Remove the absent old library entry |
| vendor/lib64/vendor.xiaomi.hardware.oldcredential-V1-ndk.so | Add the actual direct DT_NEEDED dependency of the OS4 service |

The existing miauthsecretd NDK library stays selected. The tool checks both
partition build properties and five exact stock asset hashes before emitting a
patch. No HAL interface is renamed, no placeholder library is generated, and
the stock service binary, init script, permissions and policy are unchanged.
This opt-in OS4 patch is separate from the generic handoff conversion; it must
not be applied to an OS3 extraction source.

`audit_annibale_vendor_blobs.py` checks source paths, rename destinations,
generated SYMLINK owners and SHA-1 pins separately. Absolute Android symlinks
are resolved within the supplied dump, never against host `/vendor` or `/odm`.
References to other partitions are reported separately. It does not apply blob
fixups, invent replacement paths or assert ELF/linker/VINTF compatibility.

The runtime checker now includes selected ODM init files and compares explicit
init `insmod`, `modprobe` and `rmmod` actions with the actual packaged modules and
their exported parameter metadata. Missing package targets, wrong partitions,
unreviewed options, unsupported parameters and removal of preloaded modules are
recorded with their triggers. Findings make the CLI return nonzero even if the
two loader services and firmware paths pass. Shell script bodies, dynamic
properties and actual Android init execution remain outside this check.

## Actual evidence

The old scratch build cache was unavailable at the start of R30. The R29 module
source commit and saved handoff archive were restored and the archive plus its
file manifest reverified. Kernel and DT source/build caches were not recreated.
The user's original OS4.0.6 OTA was range-read again. Both vendor and odm were
reconstructed from the same payload manifest, with operation and whole-partition
SHA-256 checks, followed by successful EROFS extraction. OTA signatures were not
verified. Both partition properties report `OS4.0.6.0.XPKCN`, Android 15/SDK 35;
these are vendor/odm properties, not the system Android version.

After the base handoff conversion: 3760 present vendor/odm list entries, 32
missing and 103 entries in other, unexamined partitions. After the OS4 AuthSecret
patch: **3762 present, 30 missing, 103 outside scope**. This is a file inventory,
not a count of working drivers. Other missing paths were deliberately not
silently deleted: old camera assets, display SR models, QESD/QSAP/SLA files and
two VPU33 firmware variants still need a reviewed version-specific decision.

Both R29 handoff families retain 217/218 modules. Their selected init view uses
96 present stock rc files plus five device-owned rc files. Blob fixups and a
complete Android install graph were not executed. The 16 explicit module
actions produce eight findings in each family:

* `nicmd.rc` requests `rmnet_perf_ingress_deag` and `rmnet_perf_opt_mode`; the
  packaged source `rmnet_perf.ko` exports neither. This does not by itself prove
  insertion fails, but the requested tuning cannot be assumed to take effect.
* Three property actions remove preloaded RMNET modules. Their intended
  lifecycle, dependencies and effects on traffic remain unqualified.
* `slad.rc` directly requests `sla.ko`, which the handoff does not package.
* The factory Wi-Fi property still names the legacy Pronto directory and module
  (two findings for one command). It is not evidence of ordinary Wi-Fi failure
  or a reason to substitute a Kiwi module without its factory-mode review.

The stock-only `dump_binder` and `msm_11ad_proxy` actions are not present in this
selected native view. They are retained only in the stock audit. Both pinned
audio asset/header/XML checks pass again. All **206 tests** pass, including a
fresh EROFS fixture made from the restored TFA module directory. This fixture is
for tests, not a newly qualified native image set.

## Use with a matching stock dump

Apply the updated base device conversion patch to the pinned reference, or the
small R29-to-R30 duplicate-entry patch to an already converted R29 device tree.
Then prepare the optional OS4 extraction-list patch:

```sh
python3 -B sm8750-modules/tools/prepare_annibale_os4_authsecret.py \
  --dump /path/to/extracted-stock \
  --proprietary-files /path/to/device/xiaomi/annibale/proprietary-files.txt \
  --output out/new-os406-authsecret
```

Review the patch and validation hashes, then `git apply --check` and apply it
to that device tree. The input dump and input list are not modified by the tool.
Run the list audit on the resulting list:

```sh
python3 -B sm8750-modules/tools/audit_annibale_vendor_blobs.py \
  --dump /path/to/extracted-stock \
  --proprietary-files /path/to/device/xiaomi/annibale/proprietary-files.txt \
  --report out/vendor-odm-inputs.json
```

A nonzero result currently reflects the 30 remaining missing inputs. Resolve
them and the other partition inputs before regenerating a complete vendor tree;
do not use empty files or keep stale generated owners to conceal the gaps.
Regeneration is also necessary to replace stale AuthSecret make/Blueprint owners.
Use the R29 handoff bytes; this round changes conversion/audit tools, not those
binaries. Keep one audio family only.

The remaining work includes actual native linker/Soong/VINTF validation of the
new library, credential services and SELinux, the module-action findings, SPSS
UEFI attach/reload, full ROM/image assembly and hardware tests. The stock init
AuthSecret boot-complete start target also differs from its service name; this
round preserves it and does not qualify eager/lazy startup. HyperOS retained
stock ownership is unchanged. No device flash or CI kernel build occurred.

Source reference: [LineageOS extraction list handling](https://github.com/LineageOS/android_tools_extract-utils/blob/lineage-23.2/extract_utils/file.py).
Exact observations: [R30 validation](annibale-r30-validation.json).
