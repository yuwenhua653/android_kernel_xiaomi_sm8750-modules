# R34: SLA lifetime and packet-path hardening

This round addresses the inherited source-level lifetime and synchronization
blockers identified in R33. The candidate remains default-off and outside all
production module lists. No loadable module, kernel image or flash package is
qualified by this work.

## Buffer and module ownership

The interface now owns a kref and a zeroed, page-aligned `vmalloc_user` ring.
`remap_vmalloc_range` replaces the slab allocation, PageReserved manipulation
and raw PFN mapping. Files and VMAs take independent references. In particular,
Linux procfs can run a file's release callback during `proc_remove` while a VMA
still exists; the file reference alone cannot keep that mapping alive.

The first successful mapping pins both the interface and module. VMA open/close
callbacks balance references for fork/split/close, preventing normal module
unload while a mapping can call its callbacks. Failed mapping attempts release
their temporary module reference. Private, oversized, offset and executable
mappings are rejected. Qualification is restricted to ARM64 with 4 KiB pages.

Disable first clears the enabled state, detaches interfaces and drains the port
table under the stats lock. It then removes proc nodes and drops owner references
outside that lock. Existing mappings retain their stopped buffer until their
last close; a new interface with the same name receives a separate allocation.
Interfaces created before `enable=1` are also cleaned up. The allocation and
partial proc-publication failure paths use the same reference discipline.

Module teardown removes the control node and drains its callbacks before taking
the control mutex, unregisters the netfilter hooks, retires interfaces, then
removes the remaining proc tree. Counter-file open/release paths also hold
interface references and access counters under the stats lock.

The relevant local kernel behavior was reviewed in
`fs/proc/inode.c` (`proc_entry_rundown`, `proc_reg_mmap`) and
`mm/vmalloc.c` (`remap_vmalloc_range`) at kernel commit
`c70ed7c690cc908451daf53c14afa8d3ceb20ca9`.

## Synchronization and packet parsing

- A control mutex serializes interface creation, enable/disable and config
  writes. The stats spinlock protects config fields, VoIP state, counters,
  interface lookup and the packet hash. Packet callbacks take no mutex.
- The old mixed-lock pseudo-RCU hash access is replaced by locked hlist access.
  Clear/delete and packet add/find now use the same lock. Config reads snapshot
  their data under that lock before formatting it.
- Header access uses `skb_header_pointer`, including the non-linear fallback,
  without assuming that a transport-header offset has been set at PRE_ROUTING.
  The parser checks IPv4/header lengths, TCP data offset and UDP length, rejects
  fragments and handles absent input/output devices. VoIP UID access requires
  a full socket.
- VoIP reads capture state once per open file and retain its text across partial
  reads. Zero-length and interrupted reads do not consume a new event.

The shared ring layouts and proc names remain unchanged; compile-time size
assertions still pass. The private producer cursor from R33 remains outside the
shared ABI. Ring entry payloads are still writable by userspace; their values
are not trusted as memory indices. Snapshot consistency and statistics semantics
are not proven equivalent to the stock implementation.

## Validation and its limits

The changed driver compiles and links to an ELF64 AArch64 relocatable `sla.o`
with Clang/LLD 19.1.7 and `KCFLAGS=-Werror`, against the same isolated Linux 6.6
GKI headers used for R33. LTO/CFI/BTF are disabled in that output. This is an
object build, not modpost, `.ko` linking, CRC/KCFI/signature or production compiler
qualification. R33's object-only reproduction command remains applicable.

Three new regression fixtures compile the actual selected driver functions,
not copied replacement implementations. They use mock kernel primitives and
UBSan with recovery disabled:

| Fixture | Cases |
| --- | --- |
| Lifetime/control | Allocation failures; either proc creation failure; a live mapping during second-node failure; duplicate/invalid interface; mmap failure/bounds/permissions; fork/close references; proc forced file release; disable before enable; re-enable with an old mapping; config copy/interruption failures and lock assertions |
| Packets | Copied header access; IPv4 options; truncated headers; bad version/length/data offset; fragments; TCP close flag; UDP bounds |
| VoIP | Open allocation failure; zero/interrupted read; partial reads across arrival of a new event; EOF and next-open snapshot |

All **229 tests** pass with the EROFS fixture and no skips. The host mocks do not
exercise real MM, procfs, netfilter concurrency or actual module unload. Their
lock assertions are not a substitute for kernel lockdep, KASAN or KCSAN runs.

Before enabling this candidate, still required:

1. Target-kernel stress of mmap/fork/split/unmap versus disable/re-enable and
   unload, allocation failure, concurrent config operations and packet traffic.
2. Matching production configuration/compiler and Module.symvers; full module
   link, exported symbol/CRC/KCFI and signing checks.
3. Annibale userspace contract checks on both HyperOS and native Android. In
   particular, mmap must use MAP_SHARED; interface-write errors are now returned
   to the caller, and VoIP state is consumed per open-file snapshot. Repeated
   pread/polling on one descriptor must be checked against actual consumers.
4. Device functionality and performance measurements. This remains a statistics
   collector, not proof of end-to-end SLA/network acceleration support.

The R33 input inventory is unchanged: **3872 present / 23 absent / 0 outside
scope**. Those are extraction entries, not driver counts. No absent userspace
service was removed or replaced by this kernel change, and no full vendor or
ROM was built this round.

Evidence: [R34 validation](annibale-r34-validation.json),
[R33 source/provenance and object build](annibale-r33-sla-product.md).
