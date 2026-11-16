# R18: touch lifecycle and interactive source dependencies

R18 changes the candidate touch driver and extends source module qualification
from audio/network to UFS, display, GPU, touch, NFC, PMIC haptics and keys. These
drivers were already compiled; their explicit installation and DT supplier
dependencies were missing from the smaller R17 plan. No new standalone driver
is imported, and this is still not a complete native ROM or a flash package.

## Touch fixes

The imported panel notifier worker had one static retry counter shared by all
touch instances. It stopped permanently after a few attempts even when the
display was still deferring probe. R18 retries genuine `-EPROBE_DEFER` panel
lookups without that ceiling, until registration succeeds or the device stops.
Missing/malformed phandle lists and permanent notifier registration errors do
not spin forever. Transient notifier allocation/defer errors retry; an occupied
client slot is not stolen. Parsed OF node references are released on all paths.

A bind/unbind mutex prevents live work from being reinitialized. A separate
work/notification mutex gates queueing and stops the worker before cancellation.
This distinction matters because this Qualcomm notifier's unregister API does
not wait for a callback whose handler was already copied out of its registry.
Once stopping begins, that late callback cannot enqueue new suspend/resume work.
Unregister is safe before initialization, is idempotent, and checks the owning
device. Goodix remove and shutdown stop display notifications before controller
resources or power are dismantled. Shutdown now checks the driver pointer before
its first dereference.

The charging-state helper now releases every `power_supply_get_by_name()`
reference, including online and property-error paths. Wireless-first status
precedence remains unchanged. This is reference cleanup, not a demonstrated
charging, touch sensitivity, or standby-power fix.

The host fixture compiles the actual changed C functions, rather than a copied
model. It exercises twelve deferred attempts on each of two panels, missing
phandles, duplicate bind, wrong-owner/idempotent unbind, transient/permanent
registration failures, an injected late callback and balanced node references.
It also checks all 64 combinations of wireless/USB presence, read errors and
online status for balanced power-supply references. These are synchronous
failure-injection tests with UBSan, not a kernel concurrency stress test.

The port remains the Warsaw-family Goodix candidate because the published
Annibale release omits its P11 touch directory. THP firmware/userspace behavior,
trusted touch, full hot-unplug teardown (including the vendor temperature
thread, mmap users and other callbacks), and real suspend/resume are still
unverified. No firmware programming policy is changed by R18.

## Expanded partition candidates

Use `annibale-interactive-tfa-partitions.json` or the SIA counterpart with the
R17 staging tool, selecting the same amplifier family in the DT. The earlier
audio-only plans remain available. Never union the two families or append
stock modules to the source lists.

| Plan | vendor_boot | system_dlkm | vendor_dlkm | Total |
| --- | --- | --- | --- | --- |
| TFA | 66 | 1 | 119 | 186 |
| SIA | 66 | 1 | 120 | 187 |

Each plan adds 64 modules relative to its R17 audio/network subset. Reviewed
board edges connect display to SUN clock/interconnect/regulator providers,
GPU to GPUCC/GCC/RPMH, Goodix to its GENI SPI/GPI/TLMM/rails and display,
NFC to GENI I2C/TLMM, haptics to SPMI/SDAM, and UFS to its SUN PHY and clocks.
The fixed panel/touch regulators and GPIO-key driver are already built in.
This is a selected supplier review, not exhaustive DT dependency discovery.

The source UFS graph exposes a concrete first-stage inversion when using stock
placements verbatim. `ufs_qcom` needs `qcom_ice`, which imports
`tme_hwkm_master_broadcast_transportkey` from `tmecom_intf`. The stock normal
list places the latter in vendor_dlkm. It cannot be used there to load the
source storage chain needed before that partition is mounted.

The native plan explicitly moves only this provider to vendor_boot and orders:

`qcom_ipcc -> msm_qmp -> tmecom_intf -> qcom_ice -> ufs_qcom`

The first two edges come from Sun's TME mailbox DT wiring, not ELF symbol
imports. The existing source modules supply the interfaces; no CRC replacement,
fake exports or stock/source mixing is introduced. Moving TME back to the late
partition is a negative validation case and must fail. Module insertion still
does not prove TME firmware, encrypted UFS access or a successful device probe.

```sh
python3 -B sm8750-modules/tools/stage_annibale_android.py \
  --kernel-out out/annibale-btf \
  --module-stage out/annibale-modules-r18/MODULE_STAGE \
  --policy sm8750-modules/Documentation/xiaomi/annibale-interactive-tfa-partitions.json \
  --depmod tools/kernel-build-tools/linux-x86/bin/depmod \
  --strip tools/clang-selected/clang-r510928/bin/llvm-strip \
  --odm-root /path/to/exact/OS4/odm --output out/annibale-interactive-tfa
```

Replace MODULE_STAGE with the successful R18 audio-profile build. R18 rebuilt
all 91 external modules with strict joint modpost against the unchanged R14
kernel. Both actual stages pass ARM64/CRC/vermagic/BTF, strip-invariance and
Android dependency-path checks. Build warnings are retained in the report;
success is not a warning-free claim. The ready property still means only that
the selected partial list was inserted, not that the complete device is ready.

## Combined DT and remaining work

The devicetrees repository adds `tools/validate_annibale_interactive.py` to
compose the existing SoC/audio, common and Annibale camera, P11 display and
matching SUN/SUN-v2 GPU overlays across eight bases and both amplifier families.
It checks touch panel references and firmware names, selected audio/DMIC
bindings, GPU/UFS/TME providers and unchanged camera sensor properties. This
does not select the user's actual panel, amplifier or SoC revision, validate
all GPIO conflicts, or create a bootloader DTBO table. Existing DTC warnings
are recorded rather than hidden.

Xiaomi display feature hooks and ABI, exact P11 touch/THP compatibility, camera
extensions/HALs, complete charging policy, final ROM ownership conversion,
signatures/AVB and enforcing init/probe behavior remain open. The built camera
driver is not added to this particular runtime list merely because its DT is
included for cross-overlay regression checking.

HyperOS retains its coherent original module family and loader policy. The
fresh independent stock audit still reports eight unresolved normal/recovery
variants and no newly detected ABI blocker. No native-only TME move or touch
candidate is installed into HyperOS, and neither ROM path is boot-qualified.
