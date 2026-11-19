# R47 ARM64 qualification

R47 serializes RMNET offload table drain and state destruction against the
offload parameter callback. RCU readers are drained before acquiring the lock;
the RCU wait is never made while holding that lock. Both source variants and
their teardown ordering regression fixture are updated.

## Failed qualification and correction

Run 44478505057, attempt 2, job 135413374161 completed the host regression
checks, then failed before compiling any kernel code:

```
ValueError: toolchain size/hash differs: bison-data
```

The old downloader pinned the transport tar.gz bytes. The correction uses
shallow sparse Git checkouts of the same four full AOSP commit IDs, with Git
object checking enabled and explicit HEAD verification. It does not substitute
system toolchains, move to a branch tip, or accept an arbitrary replacement
archive hash. The original log did not record the downloaded size/hash, so the
specific cause of the archive mismatch is not established.

An offline integration fixture creates a real local Git remote, advances its
branch, and checks that acquisition still returns the pinned content and only
the selected subtree. It also rejects moving refs, escaping paths and missing
subtrees. This fixture runs before the expensive kernel checkout/build.

CI now saves the complete acquisition/build console log even if it fails
before creating kernel output. Dependency installation has a ten-minute step
limit and bounded HTTP timeouts. Kernel module packaging resolves modules.order
entries to .ko files and rejects paths outside the kernel output.

The Windows sandbox did not permit creating the test fixture's .git/config;
only Python syntax validation was completed locally. The Git integration
fixture and ARM64 build must pass on the Linux runner before claiming success.

## Subsequent run and long-path fix

Run 44481852464 completed all 25 host test executions, verified all four AOSP
Git toolchain commits, and linked Image plus the in-tree modules. It then
failed during external WLAN compilation. The complete build.log in diagnostic
artifact 14510781537 identifies the first failure:

```
make[4]: /bin/sh: Argument list too long
.../qcacld-3.0/core/hdd/src/wlan_hdd_assoc.o] Error 127
```

The standard Actions workspace repeats the long repository name twice.
Repeated absolute WLAN include paths make the shell command exceed its
argument limit. CI now creates fresh local shared Git clones at a short
physical /tmp/ak.XXXXXX root, verifies every copied HEAD, and builds there.
The original checkouts remain intact for Actions cleanup and Git object
storage. This is a real short source/output path, not a symlink subsequently
expanded by Path.resolve(). The entry point rejects physical roots longer
than 32 bytes before tool acquisition or compilation.

Artifact collection follows the short root. On failure, the external builder
prints the first error context as well as the tail. The prior tail omitted
the shell error. No driver/configuration or strict linking checks are disabled.
This correction passed the complete ARM64 qualification described below.

## Successful qualification

[Run 44487958049](https://github.com/yuwenhua653/android_kernel_xiaomi_sm8750-modules/actions/runs/44487958049)
built module source commit `53e21323104f0ad3f5596a2032b95d676b92ed6d` with the
unchanged core and device-tree pins. Job 135436063908 completed successfully.

- 25 host test executions passed, including acquisition, flow matching and
  module lifecycle/teardown checks.
- Image and 411 in-tree modules linked; all 94 selected external modules linked.
- All 505 modules passed the same-build ARM64/BTF/vermagic/CRC/dependency checks.
- The source tree was clean; all recorded kernel inputs remained unchanged
  during the external build. Source hashes cover 9,447 staged files.
- Kernel release: `6.6.144-4k-gc17ffa89f4fe`.
- `rmnet_offload.ko` SHA256:
  `09aac5dca74bfe09af01378d8a09722709973682d9eb90e36db364e0f12a8747`.
- Qualification ZIP SHA256 (inner ZIP):
  `b85e97c9d80e1edab54d6b0d5baae13a1c665dd00d37b58f41e598804742f949`.

[Diagnostics](https://github.com/yuwenhua653/android_kernel_xiaomi_sm8750-modules/actions/runs/44487958049/artifacts/14512618476)
and [qualification binaries](https://github.com/yuwenhua653/android_kernel_xiaomi_sm8750-modules/actions/runs/44487958049/artifacts/14512543869)
are retained by this run until 2026-12-03. The diagnostics were downloaded and
their build, verification and provenance records checked after completion.
The large binary download could not be completed locally; its content checks
are the runner's checks, not an additional independent local binary audit.

These RMNET changes reside in external modules. Replacing only boot while
retaining OEM DLKM partitions does not exercise them. Applying them to HyperOS
requires a reviewed source/OEM module selection and matching partition/load
integration; this run does not produce that installation package.

## Scope

The qualification includes Image, in-tree modules and the selected external
audio/network/platform profile with experimental SLA. Strict modpost, BTF,
same-build CRC, vermagic and module dependency checks remain enabled. Outputs
are explicitly not flashable; no OEM mixed-module or hardware qualification is
implied.
