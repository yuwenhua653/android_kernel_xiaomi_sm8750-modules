Latest: [R14 native load dependencies and partition staging](annibale-load-integration.md).

# R13: Kiwi-v2 WLAN and IPA/RMNET source integration

The `network` profile adds **14 modules** to R12: Kiwi-v2 qcacld, three IPA/GSI
modules and ten RMNET modules. All **88 external + 411 kernel modules** pass
strict joint modpost and the cycle-aware post-link verifier. The unchanged R10
kernel is still an experimental qualification build. Wi-Fi connectivity,
cellular data, tethering, firmware interaction and native/HyperOS boot have not
been tested on a device. See `annibale-r13-validation.json` for exact evidence.

| Group | Newly linked modules |
| --- | --- |
| WLAN data path | `qca_cld3_kiwi_v2` |
| IPA/GSI | `gsim`, `ipam`, `ipanetm` |
| RMNET core/control | `rmnet_core`, `rmnet_ctl` |
| RMNET extensions | `rmnet_mem`, `rmnet_aps`, `rmnet_offload`, `rmnet_perf`, `rmnet_perf_tether`, `rmnet_sch`, `rmnet_shs`, `rmnet_wlan` |

These names occur in the exact OS4 vendor_dlkm load list. This supports the
profile choice, not a claim that every optional extension is needed on this
board. The matching CNSS, WLAN QMI, SMEM mailbox, MHI and cfg80211 providers are
included in the same source validation. No proprietary firmware or calibration
files are added to this repository.

## Build fixes

IPA and RMNET Kbuild files previously prepended `srctree` to an already absolute
external `src` path. They now distinguish absolute and relative paths when
resolving include directories and trace headers. The existing in-tree relative
path behavior is retained.

The aggregate build uses `MODNAME=annibale` for other Qualcomm components.
An optional `WLAN_MODNAME` overrides it only inside qcacld's Kbuild, selecting
`qca_cld3_kiwi_v2`. The existing `sun_gki_kiwi-v2` profile and real `cmn`/`fw-api`
sources are staged with validated relative links. Actual compiler commands were
checked: WLAN has `MULTI_IF_NAME=kiwi_v2`, while audio and display keep `annibale`.
The helper disables the separate IPA kernel-test module for this profile.
There are no driver C changes, checksum rewrites, symbol stubs, warning bypasses
or kernel configuration changes in this round.

## Reproduce

Use the `annibale` branches of the kernel and modules repositories. After the
complete matching kernel build, run:

```sh
python3 -B tools/build_annibale_modules.py \
  --profile network \
  --kernel /path/to/kernel/xiaomi/sm8750 \
  --kernel-out /path/to/out/annibale-btf \
  --clang-bin /path/to/clang-r510928/bin \
  --kernel-tools-bin /path/to/kernel-build-tools/linux-x86/bin \
  --output /path/to/out/annibale-network --jobs 6
```

The `media` and `platform` profiles remain available. The helper requires every
selected network module and uses one real modpost across all groups. The final
run performed a full build, then verified source/link identity and reran the
incremental build using the updated verifier. All 38 module-tool tests pass.

## Loading dependencies and native ROM assembly

The verifier now rejects hard dependency cycles, including self-dependencies,
and records a dependency-first order. Previously it checked that providers
existed, but not whether their dependencies could be loaded without a cycle.
The 499-module graph has no hard cycles. The 14 network roots require a closure
of **69 source modules**; packaging only the 14 new `.ko` files is insufficient.

The recorded order is not `modules.load`: it does not model softdeps, DT probes,
firmware readiness or boot-stage availability. Module provenance (kernel or
external source) does not alone determine its partition. A native device tree
still needs explicit owners and partition placement for vendor_boot,
system_dlkm and vendor_dlkm.

The normal stock lists were checked as a reference, keeping recovery separate:

| OS4 list | Unique names | Same-name source outputs | Names without source output |
| --- | --- | --- | --- |
| vendor_boot | 150 | 115 | 35 |
| vendor_dlkm | 385 | 281 | 104 |
| system_dlkm flattened list | 78 | 77 | 1 (`tls`) |

Vendor_dlkm contains 547 entries but only 385 unique names. These inventories
are not readiness percentages. For example, the early-boot differences include
Xiaomi policy/telemetry modules, while vendor_dlkm includes optional tests and
multiple amplifier variants. The source gauge also uses a different name.
Do not enable everything merely to match the counts, silently discard required
entries, or copy the stock lists unchanged into a native ROM. Review each
remaining requirement against the chosen ROM and actual Annibale DT/hardware.
This round records those gaps; it does not create an install manifest or images.

## HyperOS remains an independent path

The dual-ROM check still reports `native=passed`, `stock=incomplete_inventory`.
The exact 637 stock binaries have no detected ABI blocker against the unchanged
kernel, with R11's eight unresolved inventory variants still present. This
check models retaining the stock module providers.

A separate comparison of the 14 new source modules finds retained-stock import
CRC differences in `ipam`, `ipanetm`, `rmnet_offload`, `rmnet_shs` and
`qca_cld3_kiwi_v2`. Some GSI/IPA/RMNET exports also differ. They must use their
matching source providers; these results do not approve isolated replacement
of stock modules. A source-family link pass cannot substitute for HyperOS ABI
checks, and a stock ABI pass cannot establish native ROM integration.

Next requirements are the reviewed native partition/load policy, Xiaomi
hardware/HAL extensions and full charging stack, followed by firmware, DT,
signature/CFI/BTF and hardware validation on both ROM paths. No flashable package
is produced and no new phone test is requested from this compilation milestone.
