# R38: supply a signed eSIM input without changing the stock dump

The native OS4 profile can now obtain the missing `EuiccGoogle` APK from a
separately pinned annibale vendor source. The stock OS4.0.6 CN dump still has
**3879 present / 9 missing** inputs. With this explicit supplement, the combined
inventory has **3880 present / 8 missing**, all eight remaining in QESD.
This is an extraction/input fix, not an additional kernel driver or proof of
working eSIM hardware. It does not enable eSIM on a SKU without an eUICC.

## What changed

The old mi_ext source mapping is replaced with the supplement's real product
path and an extract-utils SHA-1 pin. A separate SHA-256 profile verifies the
exact bytes before staging. The destination remains
`product/priv-app/EuiccGoogle/EuiccGoogle.apk`, with `PRESIGNED` retained.
The helper produces a reviewable patch and a separate source directory. It
never writes into the firmware dump or the input device tree.

Source: [SM8750-AB/vendor_xiaomi_annibale at 5d498c3f](https://github.com/SM8750-AB/vendor_xiaomi_annibale/tree/5d498c3ffd6260c6b9817aa417f4c44d639a2376).
This is a community annibale vendor input; it is **not represented as an
OS4.0.6 CN stock file**. Its original firmware release is not asserted here.
The APK is not committed into this kernel source repository.

The APK declares `com.google.android.euicc`, version `226815`, minimum API 29
and target API 35. Actual Android `apksigner` verification passes APK Signature
Scheme v3 and SourceStamp. Its signer SHA-256 is
`7e26b6d5802a16799448ad635868f0345d6730310634684c0ae44e7e9f7ea764`.
The helper validates the signature and expected signer, not merely the presence
of a signing certificate. Neither the APK nor its manifest is rewritten.

`com.android.euicc.service.EuiccServiceImpl` is exported, protected by
`android.permission.BIND_EUICC_SERVICE`, and advertises the EuiccService action
with positive priority. The two window extension libraries are optional.
The existing product privilege allowlist covers the reviewed permissions.
The API >= 37 check from R37 stays in effect for the OS4 telephony APKs.

`XiaomiEuicc` depends on LineageOS `EuiccPolicy`, but that package only controls
whether the Google application is enabled. It does not implement an LPA service
and cannot satisfy this missing input by itself. Source reviewed:
[EuiccPolicy 3b3c28e8](https://github.com/LineageOS/android_packages_apps_EuiccPolicy/tree/3b3c28e8e537ffd182def2dedde3987b01a60f0f).

This Google LPA is a candidate for a native ROM with a compatible Google
services configuration. A Google-free LPA solution, framework compatibility on
API 37, feature/overlay selection by actual SKU, modem/eUICC access, carrier
activation and profile download remain unverified. No duplicate LPA should be
installed by a separate GMS package. No SKU, feature flag or modem setting is
changed by this patch. Retained-stock HyperOS handling is unchanged.

## Prepare and extract after R37

Use `androguard==4.1.3` and Android `apksigner` (35.0.2 was used for verification).
Download the exact pinned input, then run the helper. A local APK from that
same source can be supplied instead; different bytes are rejected.

```sh
curl --fail --location --output EuiccGoogle.apk \
  https://raw.githubusercontent.com/SM8750-AB/vendor_xiaomi_annibale/5d498c3ffd6260c6b9817aa417f4c44d639a2376/proprietary/product/priv-app/EuiccGoogle/EuiccGoogle.apk
python3 -B sm8750-modules/tools/prepare_annibale_euicc_source.py \
  --apk EuiccGoogle.apk \
  --device-tree /path/to/r37/device/xiaomi/annibale \
  --apksigner /path/to/apksigner \
  --output out/new-annibale-euicc
git -C /path/to/r37/device/xiaomi/annibale apply \
  /absolute/path/to/out/new-annibale-euicc/annibale-euicc-source.patch
```

`--apksigner` also accepts an `apksigner.jar` path. Keep the separate `source`
directory available: this patch does not put the APK into the stock firmware.
After the ordinary stock extraction, supplement just the Euicc section from
the Android source root:

```sh
device/xiaomi/annibale/extract-files.py --section Euicc --no-cleanup \
  /absolute/path/to/out/new-annibale-euicc/source
```

The ordinary stock extraction still reports missing inputs. Do not treat its
failure as a successful complete extraction or pass the two directories as an
incremental OTA chain. The final vendor/ROM build remains blocked on unresolved
inputs. The helper and scoped command do not silently remove those inputs.

## Validation and QESD status

- **264 tests passed**, zero skipped, including invalid service contracts,
  missing privileges, required-library drift, corrupt APK rejection and retained
  signing flags.
- Real extract-utils generated **37 selected APK/JAR entries**. EuiccGoogle has
  one product privileged owner, `presigned: true`, `preprocessed: true`, no
  platform re-signing, and no skipped APK checks. Its output is byte-identical
  and passes `apksigner` again. The phone/IMS ownership checks still pass.
- Real `--section Euicc --no-cleanup` extraction supplied the pinned APK and
  preserved all **36 existing archive files**. The migration patch applied to
  an isolated R37 tree and matched the converter output.
- The complete six-partition input inventory plus the explicit supplemental
  input was audited. These are input/build-rule checks, not a full Soong/ROM
  build, SELinux compile, boot or hardware qualification.

The donor contains all eight missing QESD paths, but they are **candidates only**.
The donor and OS4 differ in `libqesdk_manager.so`, `libqesdk_ndk_platform.qti.so`,
`libqms.so`, QESD HAL libraries and other related components. Identical library
names and even resolved symbol names do not establish C++ object layout,
protocol, linker namespace, authentication or runtime compatibility. The
FrameworksUtilsSysService donor APK uses a system shared UID and non-SDK APIs;
its manifest service is `QesdkSysService`, while the retained stock shell helper
names `FrameworksUtilsService`. That is a compatibility question, not proof
that the shell helper is an APK replacement.

No QESD binary, substitute service, disabled authentication check or removed
list entry is installed in R38. The next QESD step requires reviewing this
candidate set against the retained OS4 providers and native SELinux before
integrating it. All eight entries remain explicit unresolved inputs.

Evidence: [source profile](annibale-euicc-source.json),
[migration patch](patches/annibale-euicc-source.patch), and
[validation](annibale-r38-validation.json).
