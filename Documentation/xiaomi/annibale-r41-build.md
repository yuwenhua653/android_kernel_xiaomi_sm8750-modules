# R41 — Redmi K90 / annibale fresh build qualification

2026-11-19: Linux 6.6 kernel, selected external drivers, DT containers and both
source-native offline image variants built successfully from the R40 source
state. No driver source fix was needed in this run. This is not a full ROM build
or hardware qualification; the artifacts are not a flash package.

## Evidence

| Check | Result |
| --- | --- |
| Kernel | Fresh ARM64 Image and 411 in-tree modules; 6.6.144-4k-gc70ed7c690cc |
| External drivers | 93 complete .ko links; 504 total modules passed same-build ELF/vermagic/CRC and hard-dependency checks |
| SLA candidate | Separate full .ko, modpost and BTF build with KCFLAGS=-Werror passed; remains default-off and excluded from images |
| DT | 8 base DTBs, 4 DTBO containers, 32 final compositions; power suppliers and SPSS checks passed on all 32 |
| TFA partition selection | 217 modules: 78 vendor_boot, 1 system_dlkm, 138 vendor_dlkm |
| SIA partition selection | 218 modules: 78 vendor_boot, 1 system_dlkm, 139 vendor_dlkm |
| Offline images | Both variants: boot v4, vendor_boot, DTB/DTBO, EROFS system_dlkm/vendor_dlkm assembled and checked |
| vendor_boot | Non-empty platform type 1 and DLKM type 3 entries; unpack and byte roundtrip passed |
| EROFS | LZ4 zero padding, file contents, UID/GID/modes and SELinux labels checked after extraction |
| ROM handoff | Both variants exported, with 1003 UAPI headers each |
| Tests | 315 unique cases passed across module tools (285), DT tools (15), kernel helpers (15) |

The first module-tools run skipped seven real-EROFS cases. All seven were then
covered by the 17-case image suite with a real labelled EROFS fixture; all 17
were repeated successfully against the final TFA vendor_dlkm image. Repeated
cases are not counted again in the 315 total. Build warnings were present.

## Exact inputs and reproducibility

See [machine-readable evidence](annibale-r41-validation.json) for source commits,
toolchain commits/archive SHA256, configuration, symbols, image hashes and
limits. The modules build input is R40 commit
`6e3c21785c9a8569fabe3d9a57cd182d03ec13c3`, not this report-only commit.
The external build recorded a clean source tree and unchanged kernel inputs.

The official AOSP clang-r510928 (clang 18) and kernel build tools were used with
six jobs. CFI and kernel/module BTF were enabled; LTO was disabled by the
existing qualification configuration. Core entry point:
`scripts/xiaomi/compile-annibale-board.sh qualify`.
External entry point: `tools/build_annibale_modules.py --profile audio`.
Final partition selections use `annibale-spu-tfa-partitions.json` and
`annibale-spu-sia-partitions.json`, including power, thermal and SPSS additions.
The earlier wireless-only staging outputs are not the final image inputs.
Exact executed commands and logs are retained in the R41 evidence archive.

Original OS4.0.6.0 boot and vendor_boot baselines were recovered completely from
the OTA payload. Every compressed operation and each full partition matched
its payload SHA256. OTA signature authentication was not performed. Source
modules, rather than original stock modules, populate these offline images.

## Remaining release gates

The environment has no complete Android 17 platform tree or complete regenerated
vendor tree. Therefore full ROM/Soong/SELinux compilation, platform signing,
VINTF integration, init_boot/recovery/vbmeta/super assembly and first boot remain
unverified. Wi-Fi, audio, Bluetooth, vibration, charging and standby have not
been tested on this OSS build. HyperOS compatibility is not established.

This qualification config retains an experimental empty GKI unprotected-symbol
list. Passing same-build symbol CRC checks does not establish production KMI,
module-signature acceptance or runtime CFI compatibility. SLA runtime mmap,
proc and netfilter behavior also remains unverified. Physical TFA/SIA identity
must be confirmed before selecting a device build.

The handoff exports prebuilt kernel/module outputs for ROM assembly; it does not
provide an in-ROM kernel compilation hook. For the already converted R40 device
tree, replace `device/xiaomi/annibale-oss-kernel` with the selected new handoff.
Do not reapply the historical R26 conversion patch to the R40 tree; retain the
R38 eSIM, R39 privileged QESD/platform-signing and R40 QESD integrations.
Do not flash these isolated artifacts onto retained-stock HyperOS partitions.
