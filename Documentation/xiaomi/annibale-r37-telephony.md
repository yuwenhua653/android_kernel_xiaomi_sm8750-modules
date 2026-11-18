# R37: integrated radio audio and an OS4 framework SDK check

The OS4 profile no longer requires the absent standalone QtiTelephonyService
APK. Its current QtiTelephony provider remains installed with the existing
QtiTelephonyCompat dependency. The six-partition extraction audit changes from
**3879 present / 10 missing** to **3879 present / 9 missing**. This retires one
legacy input; it does not add a driver or prove working cellular audio.

R37 also fixes a concrete native-ROM integration omission: eight selected OS4
APKs declare **minSdkVersion 37**, but the migrated device product did not check
the target framework version. An early product check now rejects a missing or
insufficient `PLATFORM_SDK_VERSION`. This is a minimum requirement, not proof
that every framework/native interface is compatible on API 37 or newer.

## Why the old APK is no longer selected

The pinned `system_ext/priv-app/QtiTelephony/QtiTelephony.apk` has the
`com.qti.phone` package, boot receiver, `ExtTelephonyService`, and the required
audio permissions. Instruction-level checks verify actual invoke operations
across 12 methods, including:

- Boot receiver starts the current service; its `onCreate` constructs the
  implementation and starts its worker initialization.
- The worker's value-added initialization calls `initQcRilAudioModule`, which
  creates/initializes `AudioControllerAgent`.
- The agent creates the audio controller and per-modem callbacks, and handles
  single/multiple SIM transitions.
- The factory constructs the AIDL or HIDL audio implementation; the AIDL path
  registers its request interface and death recipient. The audio controller
  registers an audio-server-state callback.

The inspected `persist.vendor.radio.value_add_rilaudio` query defaults to true.
No property is forced by this patch; an existing runtime override could still
disable the module. Device operation and granted permissions remain untested.

All 36 present selected APK/JAR files are hash-pinned and scanned. Their DEX and
binary manifests contain no literal dotted/slash old service package name or
`IQtiTelephonyService` descriptor. Dynamically constructed names are outside
that guarantee.

R36 conservatively left the old APK open because two stock files retained its
name. Inspection now distinguishes their roles: `telephony_packages.xml` is a
list of apps to disable on modem-less targets, while `libqcrilNr.so` uses the old
name in OEM-message/GBA/IMPI protocol symbols. Neither observation alone proves
an Android APK dependency. Together with the current service implementation and
archive scan, this supports retiring the old extraction entry for this exact
OS4 revision. Neither the modem protocol nor the disable list is rewritten.

## Native framework requirement

These selected packages require API 37 according to their actual manifests:

| Package | Selected component |
| --- | --- |
| `com.qti.phone` | QtiTelephony |
| `org.codeaurora.ims` | IMS |
| `com.qualcomm.qcrilmsgtunnel` | QCRIL message tunnel |
| `com.qualcomm.atfwd` | AT command forwarding |
| `com.qualcomm.wfd.service` | Wireless display |
| `com.qualcomm.qti.uimGbaApp` | UIM GBA |
| `com.qti.qcc` | QCC |
| `com.qualcomm.qti.poweroffalarm` | Power-off alarm |

The product guard uses the normal `PLATFORM_SDK_VERSION` and Android
`math_gt_or_eq` function. No custom build variable or shipping-API change is
introduced. Do not lower APK minSdk declarations to bypass the check: an older
native framework needs a matching older userspace set and separate validation.
This optional OS4 native profile does not change HyperOS retained-stock handling
or the Linux 6.6 kernel branch.

## Apply after R36

Use an isolated Python environment with `androguard==4.1.3` installed:

```sh
python3 -B sm8750-modules/tools/prepare_annibale_os4_telephony.py \
  --dump /path/to/extracted-os406 \
  --device-tree /path/to/r36-converted/device/xiaomi/annibale \
  --output out/new-os406-telephony
git -C /path/to/r36-converted/device/xiaomi/annibale apply \
  /absolute/path/to/out/new-os406-telephony/annibale-os406-telephony.patch
```

The converter verifies exact input/template/stock hashes, selected archive
ownership, APK manifests and the required DEX call edges. It writes a
[reviewable patch](patches/annibale-os406-telephony.patch) without modifying the
stock dump or input tree. Repeat application and input drift are rejected.

## Verification and remaining work

The patch was applied to an isolated R36 tree and both output files matched
the converter. Real LineageOS extract-utils generated all 36 selected archives;
QtiTelephony/IMS each have one privileged system_ext owner, platform certificate
selection and their existing QtiTelephonyCompat dependency. The extracted
QtiTelephony APK stayed byte-for-byte identical to stock.

All **255 tests** pass, with no skips. Nine new tests cover input/template drift,
retained compatibility dependency, repeated application and missing/ambiguous
call evidence; a string literal cannot satisfy an actual call-edge requirement.
Six separate GNU Make checks used the actual LineageOS Android math source:
unset, 35, 36 and invalid SDK values fail; 37 and 38 pass the minimum check.
This is not a complete Kati/Soong/ROM build or hardware qualification.

The remaining **nine inputs are QESD (8) and EuiccGoogle (1)**. QMS/QESDK still
contain manager/security-manager path checks and authentication references;
no matching executable or system APK was recovered. No stub, renamed binary,
verification bypass or service removal is used to hide those gaps. The eSIM
application is still absent from this CN dump. These entries remain in the list
and the full-input audit remains incomplete.

Evidence: [validation](annibale-r37-validation.json) and
[pinned assets/call requirements](annibale-os406-telephony-assets.json).
