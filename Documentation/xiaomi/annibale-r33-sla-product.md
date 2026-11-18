# R33: SLA source candidate and complete stock input scope

R33 imports an experimental same-family SLA source and checks its ARM64
compilation against the current Linux 6.6 tree. It also completes product
partition extraction and verifies its nine selected native-ROM inputs.
No new kernel image or loadable module is delivered in this round.

## SLA source and fixes

Source: [MiCode dijun-v-oss at 0b426219](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/tree/0b426219a9a24b56c1593ebc84edb8a3f3b897b0/xiaomi-modules/mi_net/slm).
The original GPLv2 notices are retained in
[`xiaomi/sla/annibale`](../../xiaomi/sla/annibale).
This is not an official Annibale source release. The R32 source review records
the original hashes; the R33 report records the modified hashes.

Changes from the official source:

- Replace removed `strlcpy` calls with `strscpy`, checking a negative result.
- Handle zero-length config writes, reject oversize writes and terminate input
  without dropping its last character when no newline is supplied.
- Reject mmap offsets, oversize mappings and executable mappings; retain the
  requested page protections, disable expansion/dumps and future execution.
- Keep the producer cursor private to the kernel. Both packet paths and
  consolidation use that cursor and constant ring bounds, rather than the
  userspace-writable `cur_idx` and `total` fields.
- Pair the VoIP `single_open` with `single_release`.
- Initialize locks/hash buckets before publishing hooks; unwind hooks/proc
  entries on init failure and publish writable config last.
- Assert the 268-byte config, 8-byte VoIP state, 16-byte entry and 20480-byte
  ring layouts at compile time. The added private cursor is outside the shared
  ring layout. These assertions do not establish behavioral equivalence.

The separate Kconfig defaults to **n** and is not sourced by production
configuration. Kbuild requires an explicit experimental config assignment.
The candidate is absent from production module profiles and load lists.
Existing HyperOS retained-stock and native handoffs are unchanged.

### Actual compile scope

Kernel commit: `c70ed7c690cc908451daf53c14afa8d3ceb20ca9`.
Debian Clang/LLD 19.1.7 compiled `stats.o` and linked the aggregate `sla.o`
with `KCFLAGS=-Werror`. Both are ARM64 objects; `sla.o` is ELF64 AArch64 REL.
This used an isolated GKI configuration with LTO, CFI and BTF disabled.
It is not the production R29 configuration or AOSP compiler qualification.
No Module.symvers was invented, no modpost checks were bypassed, and no `.ko`
was produced. KMI/CRC, KCFI, signing and runtime remain unverified.

Example object-only reproduction with Clang/LLD and normal Kbuild host tools
on PATH (use absolute paths for the three variables):

```sh
kernel=/path/to/sm8750
modules=/path/to/sm8750-modules
out=/path/to/new-sla-object-output
make -C "$kernel" O="$out" ARCH=arm64 LLVM=1 HOSTCC=gcc gki_defconfig
"$kernel/scripts/config" --file "$out/.config" \
  -d LTO_CLANG -d LTO_CLANG_THIN -e LTO_NONE \
  -d CFI_CLANG -d DEBUG_INFO_BTF -d DEBUG_INFO_BTF_MODULES
make -C "$kernel" O="$out" ARCH=arm64 LLVM=1 HOSTCC=gcc olddefconfig modules_prepare
make -C "$kernel" O="$out" ARCH=arm64 LLVM=1 HOSTCC=gcc \
  M="$modules/xiaomi/sla/annibale" CONFIG_XIAOMI_ANNIBALE_SLA=m \
  KCFLAGS=-Werror sla.o
```

### Remaining source blockers

Do not load this candidate on a device. The inherited implementation still
frees mapped buffers during disable and calls `proc_remove` while holding the
stats spinlock. Mapping/file/module lifetime, slab/PageReserved ownership,
concurrent config writes, packet hash synchronization and packet header
validation need correction and runtime tests. Fixing address bounds does not
fix use-after-free. The shared entry payload remains writable and its
concurrency/semantics also require review.

After those fixes, qualify the actual production toolchain/config, module
exports/CRC/KCFI and the Annibale userspace contract before packaging.
The missing SLA service entries in the ROM list are a separate userspace gap;
this kernel source import does not resolve them.

## Product and native-ROM input validation

The OS4.0.6 product image passed operation hashes and the full 5,493,166,080-byte
partition SHA256 (`dcbbb1a95022d1bb9e87de1ed0d9b0e39d40b9231f07bd1bc009506741008e96`).
EROFS extraction succeeded. This verifies transfer integrity against the OTA
manifest; OTA signature authenticity was not verified.

All nine previously unexamined product entries exist: `uimgbaservice.apk`,
four UIM permission XML files and four UIM framework JARs. ZIP integrity and
DEX presence were checked for the APK/JARs, and the XML library paths resolve
to extracted files. Their exact hashes are in the validation report.

Real LineageOS extract-utils at `44e3b07397a339c2721c637e40cb73159c78ad46`
copied these nine entries and generated scoped Android.bp/Make files. The
five APK/JAR owners are unique and product-specific; all four permission
copies appear once. Existing list entries required no path changes.
This is not full vendor generation, Soong or framework ABI validation.
`UimService.xml` also refers to `qti-telephony-hidl-wrapper-prd`; its target
source owner and runtime compatibility remain to be checked.

| Extraction scope | Present | Missing | Outside scope |
| --- | ---: | ---: | ---: |
| R32 five partitions | 3863 | 23 | 9 |
| R33 all six list partitions | 3872 | 23 | 0 |

The 23 absent entries still concern camera models/libraries, QESD, QSAP, SLA
services, telephony/IMS, media and eSIM. No equal-basename replacement was
found in the seven extracted partitions (including vendor_dlkm). This does
not rule out renamed replacements or source-provided components. Do not
silently delete absent entries or treat input counts as working-driver counts.

All 226 existing regression tests passed without skips, using the EROFS
fixture. They do not exercise SLA concurrency or mmap lifetime. No full ROM,
SELinux/VINTF check, device boot or hardware functionality was tested.

Evidence: [R33 validation](annibale-r33-validation.json).
Prior userspace conversion: [R32](annibale-os406-userspace.md).
