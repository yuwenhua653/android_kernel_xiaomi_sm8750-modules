# R43: RMNET lifecycle, SLA read-only mmap and Kiwi factory integration

This round fixes two real driver defects and adapts the native device tree's
factory Wi-Fi action. Redmi K90 / annibale / SM8750, Linux 6.6 only.
**No full ROM or hardware test; outputs are not flashable.**

## Changes

* RMNET perf: the successfully registered init path fell through into TCP/UDP
  cleanup. Add the missing success return in both the production obfuscated
  source and its readable mirror. Failure unwind and exit ordering remain.
  The fixture executes both actual init/exit functions with mocked providers:
  three failures and 100 balanced cycles each, under UBSan. It does not emulate
  live packet traffic, asynchronous work or unloading races.
* SLA: OS4.0.6 slad opens the statistics node read-only and calls mmap with
  length 20480, PROT_READ, MAP_SHARED, offset 0, then closes the descriptor.
  Linux 6.6 clears VM_SHARED/VM_MAYWRITE for an O_RDONLY shared mapping, while
  retaining VM_MAYSHARE. Checking VM_SHARED rejected the real consumer.
  Check VM_MAYSHARE instead; retain private/offset/size/exec rejection and the
  refcounted mapping lifetime. The host lifetime fixture exercises the actual
  read-only flags and verifies that no write permissions are added. SLA stays
  default-off and outside all selected image profiles pending runtime stress.
* Factory Wi-Fi: replace the absent Pronto insertion with Kiwi-v2's existing
  serialized con_mode callback, after vendor.all.modules.ready=1. Explicit
  ftmd true selects FTM 5; false restores mission 0. The compiled driver enables
  QCA_WIFI_FTM. No normal-boot mode switch is requested without that property.
  Add a narrow sysfs label and vendor_init write rule. A longer con_mode_
  genfscon rule preserves generic labels for con_mode_ftm/con_mode_epping,
  because SELinux genfscon matching is prefix-based. Full policy compilation
  and firmware/radio behavior remain unverified.
* Module validation now reads the actual ARM64 ELF __param relocations and
  permissions. module_param_cb has no mandatory parmtype entry, so .modinfo
  alone missed con_mode. Bad/missing/duplicate relocations fail closed.
  The new factory writes are checked for provider, permission, readiness and
  mode; 14 unrelated legacy sysfs writes are explicitly listed as unreviewed.

## Actual verification

| Check | Result |
| --- | --- |
| Fresh external build | 93 modules; strict modpost and module BTF passed |
| Same-build link validation | 411 reused core + 93 fresh external modules; 27,971 imports checked |
| Separate SLA | Full link/BTF; 57 imports checked; excluded from images |
| TFA / SIA stages | 217 / 218 modules, with the rebuilt rmnet_perf |
| Offline image roundtrip | Both boot/vendor_boot/dtb/dtbo/system_dlkm/vendor_dlkm sets passed |
| Handoff Make | Both module/load lists resolve; 8 conflicting-owner injections rejected |
| Device source | Reproduced from pinned clean reference; 27 Blueprint files parsed, 51 literal inputs resolve |
| Scoped init | 105 files / 199 services / no duplicate owners; both factory actions checked |
| Regression | 309 cases, no skips, actual EROFS and bpfmt fixtures |

The core Image, config, Module.symvers and device trees were unchanged and
reused from R41. No claim of a fresh core build. Native outputs use the existing
qualification config, which is not production GKI signing/KMI qualification.
R42 retained-stock HyperOS ABI evidence is unchanged; the native init patch is
for the rebuilt AOSP device source and does not rewrite a stock HyperOS vendor.
Neither ROM path has been runtime-validated.

## Remaining gates

The earlier **8 explicit module-action review rows become 6**, not zero:

1. SLA is still absent from selected images while stock slad.rc requests it.
2. RMNET has two legacy parameter actions (ingress_deag, opt_mode) that lack
   validated current semantics. Do not invent aliases just to accept them.
3. Three RMNET actions remove preloaded shs/perf/offload modules. The repaired
   perf init does not establish traffic-safe removal or property reachability.

These six rows are not a count of all device defects. The 14 other sysfs writes,
complete vendor regeneration, Android17 Soong/Kati, assembled VINTF, SELinux,
AVB/signatures/GKI policy, firmware, driver probing and hardware all remain gates.
No init error or checker was disabled to make this report pass.

## Reproduction and installation into a build tree

Use prepare_annibale_continuation.py with the clean device reference at
1ed1eccfa3f68e1ec440b7f5e87ac97dc89475fe. It now applies the R43 Wi-Fi patch after
R42 init-owner validation and verifies every changed file's before/after SHA256.
For an existing complete R42 converted tree, apply only
[annibale-native-wifi-factory.patch](patches/annibale-native-wifi-factory.patch).
Never apply the same conversion twice. Regenerate complete vendor separately.

Install exactly one R43 handoff at device/xiaomi/annibale-oss-kernel for native
ROM integration. This is a validated prebuilt handoff, not a source-compile hook.
The R43 offline images and standalone SLA are evidence/checkpoints, not a
flash-test package. No flashing instructions are included.

[Structured results and exact input/binary hashes](annibale-r43-validation.json).
