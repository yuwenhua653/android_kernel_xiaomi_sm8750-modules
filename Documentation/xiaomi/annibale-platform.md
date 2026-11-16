Latest: [R13 WLAN and IPA/RMNET integration](annibale-network.md).

# R12: GPU, video, EVA and wireless-platform source integration

The Annibale `platform` profile now links **74 external modules**, adding 16 to
the R10/R11 media group. Together with the unchanged 411 in-tree modules, all
485 ordered modules pass strict joint modpost and post-link ARM64, CRC,
vermagic, dependency and required BTF checks. This is source-build integration;
GPU rendering, codec operation, Wi-Fi and Bluetooth have not been tested on a
phone. Exact artifacts, dependencies and interface findings are recorded in
`annibale-r12-validation.json`.

| Group | Newly linked modules |
| --- | --- |
| GPU | `msm_kgsl` |
| Video | `msm_video` |
| EVA vision accelerator | `msm_eva` |
| Shared-memory mailbox | `smem_mailbox` |
| WLAN platform and QMI | `cnss2`, `icnss2`, `cnss_utils`, `cnss_prealloc`, `cnss_nl`, `cnss_plat_ipc_qmi_svc`, `wlan_firmware_service` |
| Bluetooth/FM power and audio transport | `btpower`, `btfmcodec`, `btfm_slim_codec`, `bt_fm_swr`, `radio_i2c_rtc6226_qca` |

These are existing LOS Qualcomm sources newly connected to the joint build,
not new Xiaomi driver imports or a claim that all compiled variants are present
on Annibale hardware. The helper supplies the real source-root variables and
stages their existing SYNX, MMRM, DSP and audio dependencies. It does not supply
fake symbols, borrow a stock symvers file or disable modpost. Kernel inputs,
configuration and Image remain identical to the previously validated build.

## Video provider correction

The upstream root Kbuild builds `msm_video` and `video`, which are alternative
implementations exporting the same VIDC symbols. The first R12 run linked both;
the final verifier correctly rejected the duplicate `msm_vidc_lossless_encode`
provider, even though its CRC was identical. No successful artifact was
reported from that attempt.

`VIDEO_DRIVER_VARIANT` now permits selecting `msm_video` or `video`; invalid
values fail. Its `all` default preserves the upstream multi-artifact behavior.
The Annibale helper explicitly selects `msm_video`, matching the exact OS4 load
list and the existing Android.mk's installed module. The final fresh build has
only one video provider. Do not include both variants in a device load set.
A regression test ensures equal CRCs never excuse duplicate export providers.

Staging also preserves and validates six relative source links, including the
shared video `driver` directories. Dereferencing those directories made
untracked duplicate source copies in earlier stages. Fresh and resumed builds
now check both link targets and file hashes, rejecting copied, changed or
escaping links. Tests cover alias edits and identical-content target swaps.

## Reproduce

Keep the original `media` profile for the 58-module baseline. Use `platform`
for the expanded 74-module group:

```sh
python3 -B tools/build_annibale_modules.py \
  --profile platform \
  --kernel /path/to/kernel/xiaomi/sm8750 \
  --kernel-out /path/to/out/annibale-btf \
  --clang-bin /path/to/clang-r510928/bin \
  --kernel-tools-bin /path/to/kernel-build-tools/linux-x86/bin \
  --output /path/to/out/annibale-platform --jobs 6
```

The helper verifies that every newly selected module exists. The 36 module-tool
tests and four GNU make video-selection checks pass. Changed source or
profile manifests require a fresh stage; unchanged stages can use the existing
`--resume-stage` flow. No kernel configuration changes or module installation
are made by this command. The R12 validation reused R10's experimental `qualify`
kernel configuration, not a finished ROM deployment profile.

Then run the [dual-ROM checks](annibale-rom-paths.md) with that new stage and the
R11 OS4 inventory. R12 returns `native=passed`, `stock=incomplete_inventory`:
all 637 stock binaries still show no detected ABI blocker against the unchanged
kernel, while the eight stock inventory variants remain unresolved.

## Preserve both ROM paths; do not mix module families

The preceding stock result models **retaining stock providers**. It does not
approve replacing an isolated stock module with a newly built one. A separate
comparison of the new modules' real imports/exports found:

| Candidate source module | Incompatible retained-stock provider interfaces |
| --- | --- |
| GPU | Six SYNX import CRC differences |
| EVA | Eleven SYNX/FastRPC import CRC differences |
| CNSS2 | 29 MHI/IPC import CRC differences and three absent WLAN QMI metadata exports |
| ICNSS2 | The same three QMI metadata exports are absent from the stock provider |

Some CNSS/IPC/EVA exported CRCs also differ. GPU lacks the stock
`mi_soc_gov_update_gpufreq` export; no consumer of that symbol was found in the
supplied stock module inventory, so this alone is not a demonstrated loader
failure. All of these observations are separate from same-build validation.
Absence of a CRC discrepancy is not proof of matching userspace ABI or firmware.

For native ROMs, build and package these drivers with their matching source
providers, including the in-tree MHI driver. For the HyperOS path, retain the
complete stock provider set until an explicitly selected replacement group
passes dependency, interface and runtime validation. Do not downgrade the LOS
source interfaces or alter CRCs just to force a single source module into the
stock stack. There are now 475 shared module names and 154 stock names without
a same-name built source output; these counts are inventories, not readiness
percentages.

## Still missing

CNSS is the wireless platform, not the qcacld Wi-Fi data path. Kiwi-v2 qcacld,
IPA/RMNET and their full dependencies remain to be integrated. Firmware,
regulatory data and board-specific transport selection remain required. FM and
other optional compiled variants must not be auto-loaded merely because they
built. Xiaomi display/camera extensions, amplifier selection, charging policy,
final DT/ramdisk/module packaging and both ROMs' hardware tests remain open.
This round does not produce a flashable installer or request another device test.
