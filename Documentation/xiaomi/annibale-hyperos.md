# R10: HyperOS module ABI work

The current OSS build is not yet qualified as a replacement for a shipping
HyperOS kernel. The device's exact HyperOS build number is still needed. The
reference inventory used here is `OS3.0.8.0.WPKMIXM`, from
`xiaomi-annibale/android_device_xiaomi_annibale-kernel` commit
`df318c6b1c81e17d4fdc0fc9333c00c4d90e928a`. That repository's commit message
identifies the firmware; it is a community extraction, not the user's verified
current phone image. Its kernel banner is Linux 6.6.77 / android15-8, while some
vendor modules carry 6.6.57 releases. Do not infer incompatibility from the
release number alone: versioned modules compare vermagic flags and symbol CRCs.

## BTF correction

The earlier host environment lacked pahole. `olddefconfig` consequently removed
`CONFIG_DEBUG_INFO_BTF` and `CONFIG_DEBUG_INFO_BTF_MODULES`, although the GKI
fragment requests BTF. The stock image's embedded configuration enables both.
`struct module` includes additional fields when module BTF is enabled, so losing
this configuration changes `module_layout` and transitively many other CRCs.

Before the environment reset, the complete R9 output had `module_layout` CRC
`0x6500052f`; all 623 distinct stock module binaries expected `0x4e276f37`.
After restoring BTF, a real ARM64 build of `kernel/module/version.o` produced
`#SYMVER module_layout 0x4e276f37` in its Kbuild command record. This establishes
one corrected ABI obstacle, not complete compatibility. The initial complete
BTF rebuild was interrupted by an environment reset; its Image/modules are not
counted as validated. Subsequent complete results must be recorded separately.

The kernel helper now requires pahole, checks that both BTF options survived
configuration, and accepts an optional AOSP kernel tools directory containing
pahole plus adjacent libelf headers/libraries. It retains ABI checks and module
signature settings; it does not overwrite CRCs or force-load modules.

Use a fresh output directory and the existing pinned clang/build-tools setup:

```sh
export KERNEL_TOOLS_BIN=/path/to/kernel-build-tools/linux-x86/bin
export OUT_DIR=/path/to/out/annibale-btf
scripts/xiaomi/compile-annibale-board.sh qualify
```

The additional tool checkout used for the object experiment is
`https://android.googlesource.com/kernel/prebuilts/build-tools` at
`c2c3319b5293bab98e2367a27e993773e698f886` (pahole v1.25). A normal system pahole
and libelf development installation can be used without `KERNEL_TOOLS_BIN`.
The helper deliberately fails if required tools/configuration are unavailable.

From the modules repository, supply the same tools and completed kernel output:

```sh
python3 -B tools/build_annibale_modules.py \
  --kernel /path/to/kernel/xiaomi/sm8750 \
  --kernel-out /path/to/out/annibale-btf \
  --clang-bin /path/to/clang-r510928/bin \
  --kernel-tools-bin /path/to/kernel-build-tools/linux-x86/bin \
  --output /path/to/out/annibale-external --jobs 3
```

The module verifier also rejects a missing `.BTF` section when the target
configuration requires module BTF. This checks presence, not runtime BTF trust.

## Compatibility audit and integration limits

The modules repository adds `tools/audit_annibale_stock.py`. It checks actual
stock imported CRCs against kernel built-ins, reads real stock export CRCs for
retained module providers, checks dependency names and vermagic flags, records
load-list gaps, and distinguishes identical duplicate files from conflicting
module variants. It reports signature trailers without treating them as trust.

The pre-reset audit inspected 1,000 files: 623 distinct binaries / 621 module
names, including duplicate partition copies and two differing module variants.
All 623 had a known kernel CRC blocker in R9, including `module_layout`.
This is the entire extracted inventory, not proof that every file loads on a
particular boot. The detailed pre-reset report was lost; these are recorded
observations, not a preserved downloadable audit artifact.

The source-built R9 battery bridge provides only measurements. HyperOS uses a
larger charging stack, including `mca_business_battery_comp.ko`; the bridge
cannot replace that policy/HAL contract. The standard board profile still
keeps experimental MCA disabled. Restoring BTF does not authorize mixing these
source modules with stock charging/display/camera modules.

Next checks are a full BTF kernel/module build and audit, the user's exact
firmware inventory, retained versus rebuilt module ownership, trusted signatures,
Android KMI/CFI/BTF runtime validation, vendor ramdisk/module load lists, DTB/DTBO,
and display/camera/audio/fingerprint/charging HAL behavior. No boot image or
flashable HyperOS package is produced by these changes.

## Run the stock inventory audit

```sh
python3 -B tools/audit_annibale_stock.py \
  --stock-modules /path/to/extracted/modules \
  --kernel-out /path/to/out/annibale-btf \
  --report /path/to/stock-audit.json
```

A blocked/incomplete audit exits nonzero but writes the complete report.
`no_detected_abi_blocker` means only that these static checks found none; it never
means verified HyperOS compatibility. Preserve `modules.load*` alongside `.ko`
files. The input can contain duplicated partition copies. Different binaries
with the same module name remain explicit unresolved inventory variants.
