# R36: OS4 camera/QAPE extraction migration, 19 remaining inputs to 10

R36 removes nine stale build inputs from the pinned OS4 native-ROM profile.
It preserves the current camera stack and the QAPE implementation already in
Perf2. This is an extraction-list repair, not nine new drivers or nine verified
hardware fixes. No binary is renamed to imitate a missing model or service.

| Legacy group | Entries retired | Evidence and retained implementation |
| --- | ---: | --- |
| Camera | 6 | All 1,945 retained camera/library/config/firmware inputs (3,990,049,972 bytes) match the reviewed inventory and contain none of the six legacy name tokens. Preserve QSegNet, its node/DSP implementation, all 18 `qsn*.bin` files and the ordinary OpenCV pair. |
| Standalone QAPE | 3 | The pinned Perf2 executable imports `BnQape`, has `registerQape` and the Snapdragon registration error path, links both Snapdragon/QAPE AIDL libraries and loads `libqape_oem_ext.so`. Preserve Perf2, Snapdragon Services, their init scripts, manifest fragments, interface libraries and configuration. |

The removed camera files are `libSEGModel.so`, the two `_se` OpenCV variants,
`seg_quantized.serialized.8750.pertensor_512_cls3r.bin`, and the old
`encoder.serialized.8750.O3.bin` / `decoder.serialized.8750.O3.bin`. The current
segmentation node contains the `libqsegnet` loader reference; its QSegNet library
contains the current `qsn` model names. Current `libopencv_imgproc.so` has the
matching SONAME and needs `libopencv_core.so`. The current models are retained;
this does **not** establish that they are interchangeable with the old models.

QAPE retires only the absent `qsap_qapeservice` executable, its `.rc`, and its
old seccomp policy. Stock CIL explicitly assigns `vendor_hal_perf_default` as a
`vendor_hal_snapx_service_qti_client`. The existing Perf2 and Snapdragon AIDL
manifest instances are validated. No new permissive rule, substitute daemon or
second service instance is introduced. Existing provider policies remain in
place; complete target SELinux compilation is still outstanding.

## Apply after R35

```sh
python3 -B sm8750-modules/tools/prepare_annibale_os4_camera_qape.py \
  --dump /path/to/extracted-os406 \
  --device-tree /path/to/r35-converted/device/xiaomi/annibale \
  --output out/new-os406-camera-qape
git -C /path/to/r35-converted/device/xiaomi/annibale apply \
  /absolute/path/to/out/new-os406-camera-qape/annibale-os406-camera-qape.patch
```

The converter verifies the exact R35 extraction-list hash, stock build,
provider hashes, retained camera inventory and legacy reference absence before
writing a new output directory. It rejects repeated application and input drift.
The [concrete patch](patches/annibale-os406-camera-qape.patch) was actually applied
to an isolated R35 tree; the resulting file matches the converter byte-for-byte.
Use the converter first to check your input rather than applying the patch to
an unreviewed firmware revision. HyperOS retained-stock handling is unchanged.

## Checks

| Full six-partition audit | Present | Missing | Outside scope |
| --- | ---: | ---: | ---: |
| R35 | 3879 | 19 | 0 |
| R36 | 3879 | 10 | 0 |

LineageOS extract-utils at `44e3b07397a339c2721c637e40cb73159c78ad46`
generated 33 scoped entries: the current provider chain and all 18 QSegNet
models. Checks confirmed unique module owners, expected vendor/ODM placement,
enabled ELF checks on the examined providers, single init-script installation,
and all four stock vendor-to-ODM `qsn` links. No retired input appears in the
scoped output. This is generation, not successful Soong linking or complete
ELF-symbol/namespace compatibility.

All **246 tests** pass without skips. Nine new checks cover reviewed input,
repeated application, provider preservation, conflicting/flagged retirements
and a reference spanning the streaming scan's chunk boundary.

Literal searches cannot exclude names dynamically assembled at runtime.
Camera modes, QAPE registration/performance, full policy/ROM builds and both
HyperOS/native hardware operation remain unverified. No new flashable image
or kernel build is claimed.

## Ten inputs remain unresolved

| Group | Count | Observed blocker |
| --- | ---: | --- |
| QESD | 8 | `qms`/`libqms` still refer to `qesdk-manager` and its security manager. The system launcher still starts `vendor.qti.frameworks.utils/.FrameworksUtilsService`, but the APK and manager executables are absent. The launcher is not a replacement APK. |
| eSIM | 1 | The EuiccGoogle APK is absent from this CN firmware; native eSIM libraries do not supply the missing application. |
| Telephony | 1 | `libqcrilNr.so` and `telephony_packages.xml` retain the old QtiTelephonyService name. The existing QtiTelephony APK alone is insufficient evidence to retire it. |

These ten entries remain in the list and continue to block complete extraction.
Recover matching implementations or verify a source-built replacement and all
its consumers before removing them. Do not substitute an unrelated device's
APK, authentication service, or empty stub to make the count reach zero.

Evidence: [R36 validation](annibale-r36-validation.json) and
[pinned migration profile](annibale-os406-camera-qape-assets.json).
