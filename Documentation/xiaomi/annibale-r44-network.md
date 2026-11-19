# R44: native network control and teardown repairs

Redmi K90 / annibale / SM8750, Linux 6.6. These are source/build qualifications,
not proof of a bootable or fully working Android ROM. No flash package is issued.

## Driver changes

* `rmnet_perf`: add a real `rmnet_perf_opt_mode` callback with all/tcp/udp/none
  modes. One READ_ONCE/WRITE_ONCE protocol mask is independent of the legacy
  TCP quickack control, which can be changed by netlink. Gate all six TCP and
  four UDP optimization call sites in both production and readable sources.
  Invalid writes return EINVAL without changing the mode. Existing queued work
  drains normally; this is not a claim that a mode write drains all packets.
* `rmnet_shs`: stop on either generic-netlink-family registration failure;
  unregister only a successfully registered family; return the original error.
  Roll back both families if netdevice notifier registration fails. Detach the
  vendor trace hook and wait for its callbacks; drain the RCU packet callbacks
  before freeing tables, low-latency state and workers. Both source versions are repaired; the production driver is kernel-built,
  and both init/control paths are host-tested.
* `rmnet_offload`: state teardown built a local flush list and then discarded
  its ownership. Deliver those descriptors back to the still-live core port
  before destroying the engine/state. Both source versions are corrected.

Actual control/init/exit/free functions are used in UBSan host fixtures.
They cover each SHS init failure, 100 balanced init/exit/teardown cycles, all
mode transitions, invalid/no-change writes and descriptor-drain ordering.
Mock RCU and tracepoint callbacks check ordering; they do not emulate kernel
scheduling, prove race freedom or qualify traffic-time module removal.

## Native vendor integration

The continuation helper now installs hash-pinned extraction fixups for OS4.0.6
nicmd.rc, init.qti.kernel.rc and slad.rc. The input is checked before editing;
changed input, ambiguous edits, changed output and accidental reapplication
are rejected. The original dump is not modified. Real extract-utils executed
all 100 selected init entries; complete vendor generation is still absent.

* All RMNET load/remove property actions wait for `vendor.all.modules.ready=1`.
  Perf modes 1/3 load the module and explicitly write all; mode 2 writes udp.
  A modprobe parameter alone was ineffective once the module was preloaded.
  Mode 3 no longer passes the removed ingress_deag parameter: current perf has
  no QMAP deaggregation implementation; rmnet_core remains its owner. This
  does not add a replacement tuning knob for legacy deaggregation behavior.
* Remove 12 dead debug/timeout writes to subsystem_restart, subsys_pil_tz,
  pil_msa and peripheral_loader. All four providers are absent from both the
  selected linked module inventory and builtin list. This explicitly retires
  unsupported controls; it does not implement equivalent modern modem knobs.
* Keep both real qcom_ramdump writes, wait for module readiness and add the
  vendor_init file permission. Give only the new perf mode node its own label
  and write rule. Complete SELinux/neverallow compilation remains unverified.
* SLA modprobe uses vendor_modprobe after module readiness, and daemon start
  and restart are guarded by readiness. This fixes load ordering/idempotence;
  it does not suppress the absent-module failure in the default profile.
* The runtime checker validates seven explicit parameter writes (two factory
  Wi-Fi, three perf mode and two ramdump). Unknown writes now fail review,
  rather than only appearing in an informational inventory.

## Explicit SLA qualification variant

`build_annibale_modules.py --experimental-sla` builds SLA in the same external
module invocation and strict modpost as the audio/network profile. The flag is
opt-in; default Kconfig and default TFA/SIA plans remain unchanged.
`prepare_annibale_sla_policy.py` extends a normal qualification plan with one
source-built vendor_dlkm SLA module. The selected variant preloads it before
modules.ready; it is not a production enablement or runtime acceptance claim.

The SLA implementation was unchanged from R43. Its actual stock-consumer mmap
contract and lifetime host fixtures were already checked; real MM/procfs,
netfilter, concurrent configuration, unload stress and statistics semantics
still require target-kernel validation on both intended ROM paths.

## Remaining gates

The old six module-action review rows are now four in the default profiles:
three RMNET runtime-removal qualifications and the deliberately unselected SLA
module. With the explicit experimental SLA profiles, the missing-module row
is resolved and **three removal rows remain blocked**. No removal allowlist or
exception was added to make those rows pass. This is not an all-defects count.
All 14 previously unreviewed sysfs writes are accounted for: 12 retired and two
adapted/checked; zero unreviewed parameter writes remain in this selected scope.

A full Android17 platform, complete regenerated vendor, Soong/Kati, assembled
VINTF, production SELinux policy, GKI/module signatures and actual device
probing/traffic/standby remain unverified. The core/DTs are reused from R41;
R42's retained-stock HyperOS ABI result remains conditional and is not a test
of these rebuilt native modules on HyperOS. Do not mix their module sets.

## Reproduction

Run `prepare_annibale_continuation.py` against clean device reference
1ed1eccfa3f68e1ec440b7f5e87ac97dc89475fe. The output includes all earlier native
conversion steps and the R44 extraction changes. Do not patch a stock vendor
partition in place or run the conversion twice on the same output.

For the experimental SLA source build, append `--experimental-sla` to the
existing audio-profile build command. Generate the matching policy with:

```sh
python3 -B tools/prepare_annibale_sla_policy.py \
  --base Documentation/xiaomi/annibale-spu-tfa-partitions.json \
  --output /path/to/new/annibale-sla-tfa-partitions.json
```

Use that policy for staging and ramdisk generation; select exactly one TFA/SIA
family. The ROM handoff is still prebuilt integration, not an in-ROM source
compilation hook. All generated checkpoints are explicitly NOT FLASHABLE.

## Completed verification

| Check | Actual result |
| --- | --- |
| Fresh build | 94 external modules; 411 reused core modules; 28,033 versioned imports checked |
| Tests | 322 passed, zero skipped; real EROFS and bpfmt fixtures |
| Default TFA / SIA | 217 / 218 modules; SLA excluded |
| Experimental SLA TFA / SIA | 218 / 219 modules; SLA preloaded |
| Four image variants | boot/vendor_boot/dtb/dtbo/system_dlkm/vendor_dlkm offline roundtrip passed |
| Four Make handoffs | Every module path/load list resolved; 16 conflicting-owner cases rejected |
| Native init | 105 files / 199 services / zero duplicate owners / seven parameter writes checked |
| Device source | 27 Blueprint files parsed; 51 literal local inputs resolve |

Every source file in the final 94-module build snapshot matches the current
source, and the recorded core inputs remain unchanged. The earlier 93-module
build was intermediate; final default and SLA images both use the final build.
No production signatures, GKI policy or runtime CFI acceptance is inferred.

[Structured evidence and binary hashes](annibale-r44-validation.json).
