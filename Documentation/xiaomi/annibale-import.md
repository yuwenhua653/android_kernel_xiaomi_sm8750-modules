Latest: [R15 opt-in smartpa source integration](annibale-audio.md).

Latest: [R13 WLAN and IPA/RMNET integration](annibale-network.md).

Latest source build expansion: [R12 platform modules](annibale-platform.md).

# Annibale module imports

Update: [R8](annibale-full-build.md) adds full touch/media/NFC/DSP module links
against a complete kernel and same-build CRC/dependency checks. The dated
object-only results below describe the initial import; hardware remains untested.

This tree contains an **experimental, opt-in** Xiaomi touch port. It has not
been loaded or tested on a Redmi K90. Matching the DT compatible strings and
module filenames does not establish a compatible touchscreen firmware, THP
userspace ABI, trusted-touch implementation, or stock kernel module ABI.

## Source and scope

The 22 C/header files under `xiaomi/touch/annibale` come from
[MiCode/vendor_xiaomi_proprietary_touch-driver](https://github.com/MiCode/vendor_xiaomi_proprietary_touch-driver/tree/57d9a0225b031f4b444251117f3ecc9deae71128/warsaw),
branch `warsaw-w-oss`, commit
`57d9a0225b031f4b444251117f3ecc9deae71128`. Individual upstream paths and
SHA-256 hashes are recorded in `annibale-touch-source.json`. Original license
and copyright notices are retained. Line endings are normalized to LF.
Fifteen upstream whitespace defects reported by `git diff --cached --check`
are removed in eight C/header files, without changing code tokens or logic.

The source release's root Android.mk routes Annibale to `p11/Android.mk`, but
the release does **not** publish that directory. The Warsaw Goodix 9916K/THP4
driver is therefore a same-family candidate, not the missing Annibale source.
The original trace header's p11 path is corroborating context only.

The official Annibale DT uses `xiaomi,touch-spi` and `xiaomi-touch`. The stock
kernel module inventory at
`xiaomi-annibale/android_device_xiaomi_annibale-kernel` commit
`df318c6b1c81e17d4fdc0fc9333c00c4d90e928a`,
`modules/vendor_dlkm/modules.load`, lists `goodix_core.ko` and
`xiaomi_touch.ko`. This port preserves those output names and exports OF/SPI
module aliases for the matching device nodes.

The existing LineageOS Qualcomm audio, display, WLAN and data drivers are
retained. Comparison against the official Annibale releases found broad older
Qualcomm changes as well as Xiaomi additions; those whole stacks are not
overlaid. Stock-loaded amplifier names alone do not prove the populated amp
hardware or validate the vendor machine-driver binding.

The reference comparison used these `annibale-w-oss` commits (read-only):

| MiCode repository | Commit | Xiaomi-specific findings |
| --- | --- | --- |
| `vendor_qcom_opensource_audio-kernel` | `9147f89e4e5814fe172f0f5cd3b774642c27c282` | Additional amplifier codecs; machine smartpa binding and some hwid-dependent routing |
| `vendor_opensource_display-drivers` | `4a586833e811c8ec53e6924116505b5724a90c2d` | `mi_disp` plus extensive DSI/SDE hooks; not independent |
| `vendor_qcom_opensource_camera-kernel` | `90523a7223f3ad562871414cd5997ece2d5a3c60` | P11 PHY tables, OIS/actuator and camera extensions; broad overlay unsuitable |
| `vendor_qcom_opensource_wlan` | `55250c04057d25d3939ae8334cca6908cde01832` | Annibale WLAN DT plus broad Qualcomm stack changes |
| `vendor_qcom_opensource_data-kernel` | `d27b4c3ec1cfdc3a75b84c8eb63f32776a922ed5` | Small smem-mailbox/build differences; no selected standalone Xiaomi module |

## Board configuration and changes

The build is disabled unless `CONFIG_TOUCHSCREEN_XIAOMI_ANNIBALE=m` is
explicitly supplied. Its Kconfig is provided for integration but is not added
to the kernel's default configuration. The Kbuild enables the candidate's
THP, THP4, FOD, and SPI CS delay paths. Factory, stylus, knock, Xring, touch
boost, MIEV telemetry and trusted-touch integration are not enabled here.

The Goodix node must provide these board-specific properties:

| Property | Annibale value | Interpretation |
| --- | --- | --- |
| `goodix,firmware-name` | `goodix_firmware_annibale` | Basename; driver appends `.bin` |
| `goodix,config-name` | `goodix_cfg_group_annibale` | Basename; driver appends `.bin` |
| `goodix,thp-config-name` | `annibale_gtp_thp_config.ini` | Complete filename passed to THP userspace |

All three properties are required and length checked. Missing values fail
probe instead of selecting Warsaw defaults. The Annibale ROM file inventory
lists these firmware/configuration files; they are not included in this
source tree. Retain the stock Annibale THP configuration and vendor variant.

The normalizer source and its already-commented startup invocation are
omitted. No Warsaw firmware, tuning CSV, or calibration blob is imported.
The driver's original normal firmware/configuration update logic remains;
its behavior on the actual controller still needs device validation.

Build files no longer depend on a proprietary tree location, wall-clock
timestamp, or display-driver Module.symvers path. The trace header uses its
local include directory. Import review also adds bounds checks for the
common ioctl payload length and the shared-memory mmap range, including
overflowing offsets and invalid area selectors. Raw IC ioctl commands retain
their byte-count ABI; other commands count s32 elements. The raw write path
rejects length underflow and reads beyond its payload buffer. The source's
local `MAX` macro is removed because the newer kernel already provides it.
This limited review is not
a full audit of the vendor userspace interface or hot-unplug lifetime.

## Dependencies and reproducible compilation

Required kernel facilities are arm64, modules, input/touchscreen, SPI, I2C,
OF, DRM, NET/netlink, POWER_SUPPLY, PROC_FS, GPIOLIB, REGULATOR, PINCTRL,
and `CONFIG_QCOM_PANEL_EVENT_NOTIFIER`. The prepared kernel used for
validation has the notifier as a module. Its implementation is in
`drivers/soc/qcom/panel_event_notifier.c`; this port does not provide a stub.
The paired Goodix module consumes exports from `xiaomi_touch`; both are
built together. QTS is not compiled: integrating it requires adapting the
candidate's relative QTS include/build path and validating trusted-touch
against the real device and userspace.

The build helper copies the source into a new staging directory. It does
not alter the kernel configuration, run vendor scripts, install modules,
flash a phone, or publish files. Prepare the desired kernel separately.

```sh
python3 tools/build_annibale_touch.py \
  --kernel /path/to/kernel/xiaomi/sm8750 \
  --kernel-out /path/to/out/annibale-board \
  --clang-bin /path/to/clang-r510928/bin \
  --output /path/to/out/annibale-touch --jobs 3
```

This defaults to `xiaomi/xiaomi_touch.o` and
`goodix_9916k/goodix_core.o`, relocatable composite objects. This is not a
loadable-module or boot validation. Add `--modules` only when the kernel
output contains a real `Module.symvers` from the matching complete kernel
build. The helper refuses this mode if that file is missing. It never sets
`KBUILD_MODPOST_WARN` or invents symbol CRCs. Final ROM packaging must not
include another touch driver that claims the same DT node.

## Validation results

On 2026-11-15, all 18 driver translation units and both composite objects
compiled and linked with the prepared LineageOS kernel, with no compiler
warnings or errors. The artifacts are ELF64 AArch64 relocatable objects.
The kernel checkout was `edf391908e89432fd4c92ec9c6bddb1a1481894e` plus
the uncommitted Annibale board changes; its prepared release was
`6.6.144-4k-gedf391908e89-dirty`. The compiler was Android clang r510928
(18.0.0). Configuration: `gki_defconfig`, `vendor/sun_perf.config`, and
`vendor/annibale_board.config` merged by the kernel preparation workflow.

Exact local invocation (the helper adds the clang directory to PATH):

```sh
PATH=/workspace/scratch/b72c45bd8860/tools/annibale-host-bin:/workspace/scratch/b72c45bd8860/tools/build-tools/linux-x86/bin:/workspace/scratch/b72c45bd8860/tools/build-tools/common:$PATH \
python3 los-work/kernel/xiaomi/sm8750-modules/tools/build_annibale_touch.py \
  --kernel /workspace/scratch/b72c45bd8860/los-work/kernel/xiaomi/sm8750 \
  --kernel-out /workspace/scratch/b72c45bd8860/los-work/out/annibale-board \
  --clang-bin /workspace/scratch/b72c45bd8860/tools/clang-prebuilts/clang-r510928/bin \
  --output /workspace/scratch/b72c45bd8860/los-work/out/annibale-touch --jobs 3
```

The resulting staging directory was `touch-1mu5e6rg/src`; the complete build
log is `los-work/out/annibale-touch-objects.log`. No output was written to the
module source checkout. `annibale-touch-symbols.json` records artifact and
configuration hashes and every undefined object symbol with its source
provider. `xiaomi_touch.o` has 109 undefined symbols; `goodix_core.o` has 147.
Sixteen Goodix references are exports of `xiaomi_touch`. Other references
have kernel export declarations, apart from `__this_module`, which is
generated during the later module build. Panel notifier registration comes
from the real kernel's `drivers/soc/qcom/panel_event_notifier.c`.

The source-level export inventory does not validate which exports the final
configuration builds, symbol CRCs, the Android KMI allowlist, or vendor ABI.
There is no complete kernel `Module.symvers` in this output, so modpost and
`.ko` linking have **not** been completed. Consequently module vermagic has
**not** been measured; the kernel release above is not a module vermagic
claim. No device loading, touchscreen operation, firmware flashing, suspend,
FOD, THP userspace, or trusted-touch test has been performed.

Five helper tests pass with:

```sh
python3 -B -m unittest discover -s tools/tests -v
```

These cover staging, source-output protection, refusal of a module build
without symbol versions, compiler-error propagation, and 15 boundary cases
against the actual C ioctl length validator, including preserving valid
257–1020-byte raw IC reads.

After the whitespace cleanup, only the eight changed C/header files were
copied over the existing `touch-1mu5e6rg/src` staging inputs. An incremental
build of the same two object targets was run with `-j2`; Kbuild's header
dependencies select the affected translation units. Its log is
`los-work/out/annibale-touch-whitespace-rebuild.log`. The provenance and
artifact hashes refer to the cleaned source and rebuilt objects.
