# R48: R47 source module assembly

This is a source staging result for Redmi K90 / annibale (SM8750).
It is not a HyperOS installer, a boot image, or proof of hardware operation.

## Inputs and provenance

- Qualified binaries: [R47 run 44487958049](https://github.com/yuwenhua653/android_kernel_xiaomi_sm8750-modules/actions/runs/44487958049).
- Kernel commit: `c17ffa89f4fe197dd0e83c36cb517b6c0c13dc34`.
- External module commit: `53e21323104f0ad3f5596a2032b95d676b92ed6d`.
- Original inner ZIP SHA-256: `b85e97c9d80e1edab54d6b0d5baae13a1c665dd00d37b58f41e598804742f949`.
- Assembly implementation: `092d6cb2a09f950b26aed6d6cb96f58dde9e45f7`.

The original R47 archive omitted `autoconf.h`, `kernel.release`, and
`modules.builtin.modinfo`. The assembler restores the recorded absolute layout,
verifies every archive member, and requires the original recorded hashes for the
regenerated configuration header and version file. It also requires the entire
505-module verification report to equal the original report.

The final kernel ELF discards `.modinfo`; that missing metadata cannot be
recovered by extracting a section from `vmlinux`. The assembler therefore runs
the pinned kernel's real `modules.builtin.modinfo` target in a separate output
directory, verifies the unchanged configuration and original built-in ownership
list, and copies only the generated metadata. It does not synthesize metadata,
suppress depmod warnings, or replace the qualified Image and module binaries.

Future qualification archives include all three previously omitted files.
Pinned Git downloads retry at most three times; five tests cover fixed commits,
invalid pins/subtrees, interruption recovery, and exhausted retries.


## Verified result (2026-11-19)

[Assembly run 44500802394](https://github.com/yuwenhua653/android_kernel_xiaomi_sm8750-modules/actions/runs/44500802394) completed successfully at 18:16 China Standard Time.
All 548 manifest entries and the 411 kernel plus 94 external modules were verified.
The restored configuration header matches its original SHA-256; the regenerated
built-in list also matches the qualified kernel exactly. All five toolchain tests passed.

| Profile | vendor_boot | system_dlkm | vendor_dlkm | Total |
| --- | ---: | ---: | ---: | ---: |
| TFA | 78 | 1 | 138 | 217 |
| TFA + experimental SLA | 78 | 1 | 139 | 218 |
| SIA | 78 | 1 | 139 | 218 |
| SIA + experimental SLA | 78 | 1 | 140 | 219 |

- [Source stage ZIPs and kernel inputs](https://github.com/yuwenhua653/android_kernel_xiaomi_sm8750-modules/actions/runs/44500802394/artifacts/14518103748) (87,935,294 bytes; not flashable).
- [Diagnostics and recovered metadata](https://github.com/yuwenhua653/android_kernel_xiaomi_sm8750-modules/actions/runs/44500802394/artifacts/14518113682).
- Artifact retention ends 2026-12-03; per-ZIP hashes are preserved in `annibale-r48-validation.json`.

No Image or external module binary was rebuilt. The separate built-in object
build produced 142,572 bytes of metadata with SHA-256
`382bb172a8cb2ed43ca6ba3edfd262a9903b92a41ba9cf861351d7525dc91b41`.

## Output scope

The four profiles are TFA, SIA, and the experimental-SLA variant of each.
Every stage carries per-file hashes, the actual partition module lists,
Android text dependency indexes, and a validation report. Module stripping must
preserve modinfo, import/export CRCs, and BTF.

The kernel input ZIP contains Image and the restored configuration/metadata.
It is not a boot image and is not a standalone replacement for the original
qualification archive when repeating full verification.

These source stages must not be copied over a HyperOS module set. A boot-only
replacement retaining OEM modules does not exercise the R46/R47 external RMNET
fixes. HyperOS installation still needs matching original partition inputs,
explicit module ownership and ABI/loader checks, and final image/runtime
validation. Native Android integration likewise needs the remaining device
coverage, firmware, init/SELinux and final image checks.
