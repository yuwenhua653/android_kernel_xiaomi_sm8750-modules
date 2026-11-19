# R42 — integration validation and source-continuation repairs

2026-11-19. The R41 kernel/module artifacts were re-used unchanged. This round
completed the available local integration and retained-stock ABI checks, fixed
one missing source file and three duplicate init service owners, and explicitly
kept unresolved gates blocked. **No full Android ROM or flash package was built.**

## Corrections

The earlier restored device worktree referenced `rootdir/etc/fstab.annibale-oss`
from both Blueprint and the ramdisk copy list, but did not contain that file.
The full R26 CLI patch already adds it; the ad hoc continuation called only
`convert()`, which changes existing files. This was a continuation error, not
a new kernel driver defect. `prepare_annibale_continuation.py` now reconstructs
all conversions and includes the canonical native fstab. The recovery fstab
is unchanged. A fresh reconstruction matched all 242 final source files.

Three services were declared in both device `init.qcom.rc` and selected OS4
vendor init files: `loc_launcher`, `time_daemon`, `vendor.msm_irqbalance`.
The patch removes the redundant device declarations and keeps the OS4 owners.
Credentials, groups, classes, capabilities and disabled options match exactly;
loc_launcher uses the canonical `/vendor/bin` spelling. Other service/action
sections remain unchanged. The extraction list still includes each retained
owner. This correction applies only to the native device tree.

The runtime checker now rejects duplicate owners across all selected service
names, not only the two module loaders. Explicit overrides remain review items.
The local-input checker uses actual AOSP bpfmt parsing and verifies literal
local file references, including globs. It records module references and
computed/external inputs as unverified instead of pretending to resolve Soong.

## Actual results

| Check | Result |
| --- | --- |
| Device inputs | 27 Blueprint files parsed; 51 literal local references resolve after fstab repair |
| Kernel handoff Make | TFA 217 / SIA 218 modules; every path exists; load lists, init_boot selection and DLKM fragment checked |
| Owner guards | Eight conflicting stock module/init_boot owner injections rejected across both variants |
| Init generation | 100 real selected OS4/supplement inputs processed by extract-utils, including normal fixups |
| Native init graph | 105 files; 199 distinct service names; duplicate owners reduced from 3 to 0 |
| Native module actions | 16 explicit actions checked; 8 review rows remain for each variant |
| HyperOS normal boot | 629 module names selected; no detected static ABI blocker |
| HyperOS imports | 29,169 built-in CRC checks and 4,901 retained-provider CRC checks |
| HyperOS first stage | 150 load-list roots; 150-member hard-dependency closure; no missing/later-partition provider detected |
| Regression tests | 298 module-tool cases passed, no skips; actual EROFS and bpfmt fixtures |

OS4.0.6 vendor_dlkm, system_dlkm and init_boot were fully reconstructed and
matched the OTA manifest's whole-partition SHA256. The exact vendor_boot already
verified in R41 supplied its module files. The inventory contains 1,009 module
files, 631 unique binaries and 629 names. Recovery is outside this normal-boot
scope. Vendor/odm init files were selectively recovered, not full partitions;
compressed payload operations were SHA256 checked. OTA signature authenticity
was not verified.

The normal-boot ABI result is **conditional**: zram/zsmalloc must successfully
load from vendor_boot before system_dlkm. The all-inventory checker correctly
continues to return `incomplete_inventory` because it does not select between
those variants. No signature, GKI policy or CFI runtime acceptance is inferred.

## Remaining module-action review

These eight rows were already known in earlier native-init review; R42
reproduces them with fresh R41 modules and the R40 extraction list:

* SLA: one post-fs-data insmod requests sla.ko, which remains default-off and
  absent from the selected images. R41's isolated SLA build does not authorize
  enabling its runtime behavior.
* RMNET: two parameter-setting actions use names absent from both selected
  source and stock module metadata; three actions unload preloaded modules.
  Property reachability and unload/reload traffic behavior remain unverified.
* Factory Wi-Fi: one Pronto insertion produces two findings (old module directory
  and absent pronto_wlan), while the source profile builds Kiwi-v2. Do not
  substitute modules solely to silence the checker.

No init actions, module checks, signature checks or SELinux rules were disabled
to turn these unresolved results into a pass. The three duplicate declarations
above are the only init behavior-source changes in this round.

## Reproduce the corrected source tree

Use a clean reference device repository at
`1ed1eccfa3f68e1ec440b7f5e87ac97dc89475fe`:

```sh
python3 -B sm8750-modules/tools/prepare_annibale_continuation.py \
  --reference reference-annibale-rom --output out/annibale-r42-device \
  --report out/annibale-r42-source.json
python3 -B sm8750-modules/tools/check_annibale_local_inputs.py \
  --tree out/annibale-r42-device --bpfmt /path/to/aosp/bpfmt \
  --report out/annibale-r42-local-inputs.json
```

Place that tree at `device/xiaomi/annibale` in the selected Android 17 source
checkout, and one R41 handoff at `device/xiaomi/annibale-oss-kernel`. For an
already complete R40 conversion, apply only
[the init-owner patch](patches/annibale-native-init-owners.patch), and verify the
native fstab exists; do not reapply the R26 conversion to an already converted
tree. Regenerate the complete vendor using OS4 and the R38-R40 supplements.
The helper does not generate proprietary data or run a ROM build.

A full Android 17 platform and complete regenerated vendor are still absent
here. Soong/Kati, SELinux, assembled VINTF, AVB/recovery and firmware/HAL behavior
must be checked before any flash test. Both intended ROM paths still require
real hardware testing. [Structured evidence](annibale-r42-validation.json)
and [init owner comparison](annibale-native-init-owners.json) record the limits.
