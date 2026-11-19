# R39: QESD system service input and privileged installation

R39 supplies one of the eight remaining R38 inputs, the QESD system APK, and
fixes its native-ROM installation mapping. **Seven inputs remain unresolved**:
the two manager executables, their two init files, two seccomp policies and
the manager VINTF fragment. This counts source inputs, not working drivers or
hardware features. R38's separate eSIM supplement is still required.

## Concrete installation fix

The old extraction entry installed `FrameworksUtilsSysService` under
`system_ext/app`. Both the recovered OS4 policy and the reviewed LineageOS
Qualcomm system policy select its dedicated domain with:

```text
user=system seinfo=platform name=vendor.qti.frameworks.utils isPrivApp=true domain=vendor_qesdk_app type=system_app_data_file
```

The ordinary-app path cannot satisfy `isPrivApp=true`. The dedicated policy
contains `add_service(vendor_qesdk_app, vendor_qesdk_service)`, and the service
context maps `vendor.qti.qesdsys.IQesdSys/default` to that type. R39 remaps the
APK to **system_ext/priv-app**, retaining the default **platform certificate**
selection in extract-utils. No broad allow rule, permissive domain or duplicate
service label is added.

The donor APK's original signature must not be preserved in a native ROM:
its manifest requests `android.uid.system`, so it must be signed with that
ROM's platform key. The source APK stays byte-identical during extraction;
actual re-signing is left to the Android build and has not run in this round.
Do not install or push the staged APK directly onto stock HyperOS.

## Reviewed service contract

The source is pinned to
[SM8750-AB/vendor_xiaomi_annibale, 5d498c3f](https://github.com/SM8750-AB/vendor_xiaomi_annibale/tree/5d498c3ffd6260c6b9817aa417f4c44d639a2376).
It is an external supplement, not an APK recovered from the CN firmware.
The SHA-256 is
`c23513b5caacc16ce7e438389fa58a333d7a3096792853a677b30adf30af89bd`.

Checks on the actual APK establish:

- Package `vendor.qti.frameworks.utils`, system shared UID, minimum API 31,
  target API 36, device-protected storage and direct-boot awareness.
- Both locked-boot and boot-completed broadcasts lead to its receiver.
  DEX call checks follow `startService`, construction of `QesdkSysServiceImpl`,
  and `ServiceManager.addService` for the expected Binder instance.
- The implementation returns interface version **4** and hash
  `60370da086910c28180728ea367e33077d921e8f`. The independently recovered
  OS4 `vendor.qti.qesdsys-V4-ndk.so` contains the same interface hash.
- No native library entries, declared shared libraries or JNI methods were
  found in the selected APK. This avoids introducing the candidate managers'
  unreviewed C++ library coupling in this step.
- The retained OS4 framework VINTF fragment declares the same service instance.
  That fragment omits an explicit version; R39 does not rewrite it or claim
  that it explicitly declares version 4.

The old stock shell helper's `.FrameworksUtilsService` component is not used as
the donor's startup route. The donor starts its own `QesdkSysService` through
its boot receiver. No replacement shell service is synthesized.

Policy source inspected:
[LineageOS/android_device_qcom_sepolicy, a8385f33](https://github.com/LineageOS/android_device_qcom_sepolicy/tree/a8385f33b31aac5ba7f001413f4d67c7c9bf632e).
The checks pin the actual selector, service-context and registration-policy
files. They are source checks; complete policy expansion/compilation and the
domain selected by a running ROM remain unverified.

## Apply after R38

Use an isolated Python environment with `androguard==4.1.3`. Supply the exact
OS4 dump or the recovered selected stock files, the reviewed Qualcomm system
policy checkout and the R38-converted device tree:

```sh
curl --fail --location --output FrameworksUtilsSysService.apk \
  https://raw.githubusercontent.com/SM8750-AB/vendor_xiaomi_annibale/5d498c3ffd6260c6b9817aa417f4c44d639a2376/proprietary/system_ext/app/FrameworksUtilsSysService/FrameworksUtilsSysService.apk
python3 -B sm8750-modules/tools/prepare_annibale_qesdsys_source.py \
  --apk FrameworksUtilsSysService.apk \
  --stock /path/to/os406-dump \
  --qcom-system-policy /path/to/device/qcom/sepolicy \
  --device-tree /path/to/r38/device/xiaomi/annibale \
  --output out/new-annibale-qesdsys
git -C /path/to/r38/device/xiaomi/annibale apply \
  /absolute/path/to/out/new-annibale-qesdsys/annibale-qesdsys-source.patch
```

Then supplement the separately named section after ordinary stock extraction:

```sh
device/xiaomi/annibale/extract-files.py \
  --section 'QESD system service' --no-cleanup \
  /absolute/path/to/out/new-annibale-qesdsys/source
```

Do not use the whole `QESD` section against this APK-only source: it does not
provide the retained libraries or the seven unresolved manager inputs. Full
extraction still remains incomplete. Inputs, hashes, signing rules and policy
drift are rejected for review. The script does not modify its input tree/dump.

## Validation and limits

- R38 selected source inputs were reconstructed from the pinned reference and
  converters and matched the published R38 hashes.
- **63 relevant tests passed**: 17 supplement tests (including eight new QESD
  cases) and 46 existing OS4 migration tests. Kernel/driver tests were not
  rerun; the previous full 264-test result is historical evidence only.
- Real extract-utils at `44e3b07397a339c2721c637e40cb73159c78ad46` generated the
  APK and retained manifest rules. The APK has one privileged system_ext owner
  and platform certificate selection, with no `PRESIGNED` or APK-check bypass.
- Actual scoped extraction selected the pinned APK from the supplement, kept
  an existing input, and did not request the other QESD files. The applied
  patch matched the converter's output.
- The old unpacked firmware directory had expired. Selected OS4 files were
  recovered again from the official OTA using only the required operations;
  compressed-operation SHA-256 checks passed before use. The sparse working
  images are **not complete partition images**. Whole-partition hashes and
  OTA/payload signatures were not reverified this round, and no full
  six-partition inventory was rerun. The seven-item remainder is the R38 list
  minus this one now-supplied input, not a fresh whole-firmware audit.

Binder version/hash agreement does not prove all method behavior, hidden
framework API compatibility on API 37, permissions, startup timing or callbacks.
No complete native ROM, SELinux policy or platform-signed APK was built; QESD
and OSS boot remain untested on hardware. HyperOS retained-stock handling and
the Linux 6.6 drivers are unchanged. The remaining managers need their C++ ABI,
security-manager interactions, authentication, namespaces and runtime reviewed.

Evidence: [profile](annibale-qesdsys-source.json),
[patch](patches/annibale-qesdsys-source.patch),
[validation](annibale-r39-validation.json).
