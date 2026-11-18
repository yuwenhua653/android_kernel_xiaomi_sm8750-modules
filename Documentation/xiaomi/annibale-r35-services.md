# R35: reduce the OS4 extraction gaps from 23 to 19

R35 works on the missing userspace inputs, rather than the experimental kernel
SLA collector. Three absent entries now select actual OS4 replacements and one
obsolete IMS JNI entry is removed with its stale symlink. Four supporting files
and the merged service's native SELinux ownership/rules are added. This is an
extraction/build-input repair, not a claim that four device functions now work.

| Previous missing input | OS4 resolution |
| --- | --- |
| `vendor/bin/hw/vendor.qti.sla.service@2.0-service` | Select `vendor/bin/hw/vendor.xiaomi.aidl.minet@1.0-service`, which implements the SLA AIDL service as well as MiNet |
| `vendor/etc/init/vendor.qti.sla.service@2.0-service.rc` | Select the matching `vendor.xiaomi.aidl.minet@1.0-service.rc` |
| `system_ext/lib64/libmmparser_lite.so` | Select `system_ext/lib64/libwfdparserlite.so`, the actual NEEDED dependency of the stock `libwfdmmsink.so` |
| `system_ext/lib64/libimscamera_jni.so` and its IMS symlink | Retire the obsolete extraction entry; retain the current IMS APK, its Java Camera2 implementation and `libimsmedia_jni.so` with its existing symlink |

## Evidence and integration

The merged MiNet executable imports `BnSlaAIDLService` and its descriptor, calls
`AServiceManager_addService` for the constructed service, and contains the SLA
registration failure message. Its exact stock SELinux CIL also includes
`hal_minetaidlservice_default` in `hal_slaaidlservice_server`. This is stronger
evidence than a filename similarity. The current device manifest already has
the SLA, MiNet and Miwill AIDL instances; it is checked and left unchanged.

The accompanying additions are `minetd`, its init script and the two MiNet and
Miwill AIDL libraries. Existing `slad`, its init/config and the SLA V1 AIDL
library are retained. The stock executable contains a message that the Miwill
feature was removed; selecting its interface does not restore that feature.
No replacement binary or fake service implementation is invented.

The actual WFD sink needs `libwfdparserlite.so`; the selected parser has that
SONAME. Its name is not rewritten to imitate the obsolete parser. For IMS, the
pinned APK contains `com.qualcomm.ims.vt.Camera2`, Android Camera2 references and
`imsmedia_jni`, without the old `imscamera_jni` token. The retained R32 scan of
1,522 selected ELF files found no direct NEEDED reference to the old JNI library.
These observations support retiring this version's stale entry, but do not
qualify video calling or prove every possible dynamic-loading behavior.

New SELinux files give the merged executable its own domain and the SLA/MiNet/
Miwill server attributes, label the daemon/socket/data paths, and supply core
binder, property and socket access. The actual stock SLA data directory
`/data/vendor/misc/sla` is also labeled. Existing old SLA types are retained.
No permissive domain, global allow or blanket module-loading permission is
introduced. Macro availability was checked against LineageOS 23.2 public
`te_macros`; the complete target policy and neverallow checks have **not** run.
Diagnostic shell subprocesses and other stock helper operations still need
target-policy/runtime review rather than broad grants guessed from names.

The stock `minetd.rc` includes TCP buffer tuning and its original daemon/socket
setup. This migration retains that script as-is; it is not a separately qualified
network-performance change.

## Applying the concrete migration

The converter requires exact R32 device-tree input hashes, OS4.0.6 vendor/ODM
properties, 17 pinned stock assets and reviewed policy-template hashes. It
rejects drift, duplicate extraction/context owners and repeated application.
It writes a patch without changing the dump or input device tree.

```sh
python3 -B sm8750-modules/tools/prepare_annibale_os4_services.py \
  --dump /path/to/extracted-os406 \
  --device-tree /path/to/r32-converted/device/xiaomi/annibale \
  --output out/new-os406-services
```

Use this after R30 base conversion/AuthSecret, R31 media and R32 userspace
migration. The exact generated [patch](patches/annibale-os406-services.patch)
is included for review. Prefer the converter before applying it so stock/input
hashes are checked. The generated patch was applied to an isolated copy of the
R32-converted reference; all resulting files matched the generator's hashes.

This is the optional OS4 native-ROM extraction profile. It does not replace
files on a running HyperOS system or enable the R34 experimental kernel SLA
module. HyperOS retained-stock handling stays separate.

## Checks and remaining entries

Real LineageOS extract-utils generated Android.bp/Make files for 14 selected
inputs including both consumers and replacements. The added service, daemon,
interface libraries and parser have unique owners on the expected partitions;
their ELF checks remain enabled. Both init scripts are installed once, the old
JNI link is absent and the retained media JNI link remains. This is scoped
generation, not a complete vendor or Soong build.

| Same six-partition scope | Present | Missing | Outside scope |
| --- | ---: | ---: | ---: |
| Before | 3872 | 23 | 0 |
| After | 3879 | 19 | 0 |

The audit correctly still returns an incomplete-input status with 19 absent
entries. No missing item is hidden by excluding a partition.

| Remaining category | Entries | Why still open |
| --- | ---: | --- |
| Camera | 6 | Segmentation/OpenCV variants and three model files lack a verified replacement/retirement decision |
| QESD | 8 | Legacy manager/security services, policies, manifest and system APK remain unresolved; current consumers still contain manager references |
| QSAP | 3 | QAPE executable/init/seccomp policy still need a verified provider mapping |
| eSIM | 1 | The old EuiccGoogle APK is absent; native eSIM components do not by themselves supply this APK |
| Telephony | 1 | The old QtiTelephonyService APK is absent; retaining QtiTelephony is not proof that it implements the former service |

All **237 tests** pass with no skips. Eight new tests cover stale/repeated input,
duplicate module/context owners, retained-input loss, policy-template changes
and missing/duplicate AIDL declarations. Full ELF symbol/namespace compatibility,
policy compilation, ROM generation, IMS/WFD/network behavior and both HyperOS/
native device tests remain unverified. No new flashable image is produced.

Evidence: [R35 validation](annibale-r35-validation.json),
[pinned assets and migration profile](annibale-os406-services-assets.json).
