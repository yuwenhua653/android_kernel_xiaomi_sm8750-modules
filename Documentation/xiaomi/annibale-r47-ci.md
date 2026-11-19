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

## Scope

The qualification includes Image, in-tree modules and the selected external
audio/network/platform profile with experimental SLA. Strict modpost, BTF,
same-build CRC, vermagic and module dependency checks remain enabled. Outputs
are explicitly not flashable; no OEM mixed-module or hardware qualification is
implied.
