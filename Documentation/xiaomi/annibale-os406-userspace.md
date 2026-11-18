# R32: OS4 userspace inputs before a full native build

R32 repairs four concrete extraction issues, checks the real ELF fixups and
generates a scoped vendor using LineageOS extract-utils. It does not rebuild or
qualify the kernel, package new kernel modules, generate a complete vendor tree,
compile a ROM or authorize a flash. HyperOS retained-stock ownership is unchanged.

## Changes

| Component | Observed OS4 dependency/input | Change |
| --- | --- | --- |
| Camera | `libmicamera_hal_core.so` and `libmicamera_hal_policy.so` both need `libcameraopt_stub.so` | Add the actual ODM library and extend the existing `libui.so` to `libui-xiaomi.so` fixup group |
| Display | ODM `hw/displayfeature.default.so` needs `libdynamicelvss.so` | Add the actual ODM library and extend the existing sensors V2-to-V3 fixup group |
| AT forwarding | Stock ships `system_ext/app/atfwd/atfwd.apk` | Replace the absent `AtFwd2/AtFwd2.apk` extraction/install path with the actual path |
| Wi-Fi Display | System `libwfdservice.so` needs `wifidisplaysession_aidl-V2-ndk.so`; vendor service still needs V1 | Select system_ext V2 and retain the separate vendor V1 library and its module suffix |

`libcameraopt_stub.so` is the name of an existing stock library. No empty or
invented implementation is introduced. No NEEDED entry is deleted to conceal
an unresolved dependency. The old camera model files remain unresolved; adding
the two libraries is additional work beyond the old missing-path list.

`prepare_annibale_os4_userspace.py` requires exact R31 list/extract-script input
hashes, matching vendor/odm build properties, and ten pinned stock asset hashes.
It verifies actual ELF NEEDED/SONAME values. It extends existing fixup groups,
checks the resulting Python AST and the selected replacement chains, and writes
one patch for `proprietary-files.txt` and `extract-files.py`. It does not execute
the supplied extraction script or alter the input dump/device tree. This is an
optional OS4.0.6 profile, not a change to OS3 inputs.

```sh
python3 -B sm8750-modules/tools/prepare_annibale_os4_userspace.py \
  --dump /path/to/extracted-stock \
  --device-tree /path/to/r31-converted/device/xiaomi/annibale \
  --output out/new-os406-userspace
```

Apply the generated patch after R30 base conversion, R30 AuthSecret and R31
media migration. The full four-patch sequence was applied to a clean reference
at `1ed1eccfa3f68e1ec440b7f5e87ac97dc89475fe`. Both resulting files matched the
generator output byte for byte; `git diff --check` passed.

## Real extraction and generation checks

The initial ELF scan covered 1,522 selected binaries/libraries. Its raw
same-partition candidate list is not a list of missing drivers: source-built
Android libraries and existing rename/fixup rules account for many candidates.
For example the existing WFD HDCP library is renamed by the extraction script;
it must not be added a second time under its old name.

On copies of the two new ARM64 libraries, the selected replacements were applied
using patchelf 0.17.2. SONAME and every unrelated NEEDED entry were preserved.
This checks the transformation, not compatibility with the target platform's
exported symbols or linker namespaces.

The generated extraction script was also run with the real LineageOS
extract-utils at `44e3b07397a339c2721c637e40cb73159c78ad46` in an isolated Android
directory layout. Ten selected stock inputs, including their actual flags,
were copied, fixed and used to generate Android.bp/Make files. The two added
libraries have ODM owners, WFD V2 and ATFWD have system_ext owners, and WFD V1
retains its vendor owner/suffix. Each selected new owner is unique. New library
ELF checks remain enabled. The existing `libwfdservice` DISABLE_CHECKELF flag
was preserved; its full ELF compatibility remains an explicit open item.

This scoped generation is not a complete generated vendor, Soong compilation,
native linker qualification, VINTF or SELinux validation. Existing libui and
sensor-interface migration rules also still need those target-build checks.

All **226 tests** pass with no skips, including altered-input/owner rejection,
repeated-application rejection and incorrect/duplicate fixup-group detection.

## Remaining input inventory

The original system and mi_ext partition hashes and operation hashes verified,
and EROFS extraction succeeded. The system image has a system-as-root layout;
its real inner `system` directory was moved into the canonical dump layout for
the path audit. OTA signatures were not verified.

| Scope | Present | Missing | Outside scope |
| --- | ---: | ---: | ---: |
| R31 vendor + odm + system_ext | 3856 | 24 | 13 |
| R32 same three partitions | 3860 | 22 | 13 |
| R32 plus system and mi_ext | 3863 | 23 | 9 |

The extra missing entry is the old mi_ext EuiccGoogle APK path. Product transfer
was interrupted before complete download/partition verification; its partial
cache is retained but none of its nine list entries is counted as present.
These are extraction-entry counts, not counts of working features.

Current QMS/QESD consumers contain explicit `/vendor/bin/qesdk-manager` and
`/vendor/bin/qesdk-secmanager` strings. Those absent service entries have not
been blindly discarded. The exact missing/unselected paths are recorded in
the validation JSON. Camera models, QESD/QSAP/SLA service entries, telephony/IMS,
media and eSIM inputs still require version-specific decisions.

## SLA source route

A concrete official same-family source is now pinned:
[MiCode `xiaomi-modules/mi_net/slm`](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/tree/0b426219a9a24b56c1593ebc84edb8a3f3b897b0/xiaomi-modules/mi_net/slm).
The inspected [Dada port](https://github.com/klarnet2009/dada-closed-modules/tree/3c6328d3485aa7a630fe39af99f5a7d3e6e4f58e/ported/sla)
has an identical header and changes only three `strlcpy` call names to `strscpy`
in stats.c. The Annibale stock module's `config_data`/`voip_state` objects are
268/8 bytes, consistent with this family. Command-literal observations and exact
source hashes are in [the source review](annibale-sla-source-review.json).

The other project's equivalence claim is not an Annibale qualification. Review
found issues to address before integration: the inherited string-copy return
test does not handle negative `strscpy` results, `stats_map` has no explicit
mapping bounds, and interface removal/unload needs mapping-lifetime review.
No candidate code has been enabled, compiled or packaged for Annibale yet.
SLA remains a real handoff gap, with a concrete source route for the next step.

Next gates remain: remaining stock inputs, complete vendor generation and target
ELF/Soong/VINTF/SELinux validation, SLA adaptation, RMNET unload/reload, factory
Wi-Fi property handling, SPSS attach/reload, full ROM/images and hardware tests.

Evidence: [R32 validation](annibale-r32-validation.json),
[pinned userspace assets](annibale-os406-userspace-assets.json).
