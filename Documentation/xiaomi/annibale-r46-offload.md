# Annibale R46: RMNET flow address-family isolation

Continue Redmi K90 / annibale / SM8750 on Linux 6.6.144.

## Driver fix

Both production and readable rmnet_offload_engine_flow_match implementations
checked transport protocol, ports and address bytes without first checking the
IP address family. IPv4 and IPv6 share address unions. Within a colliding hash
bucket, overlapping address bytes and matching ports could therefore make the
predicate accept a flow from the other family.

Reject different roh_ip_proto values before comparing address union members.
Keep empty-slot hash reuse unchanged: empty nodes have no valid headers and
their headers are replaced when the next packet is added. No exported symbol,
module parameter, structure layout, Kconfig or DT change is made.

This is a demonstrated predicate defect. The fixture does not demonstrate an
end-to-end packet-path failure or qualify module unloading under traffic.

## Completed validation

Source commit: 5b13cf6bbabec6cbc3de336b27083626699f8304.
[GitHub Actions run 44477001118](https://github.com/yuwenhua653/android_kernel_xiaomi_sm8750-modules/actions/runs/44477001118)
completed successfully.

- GCC and Clang each compiled and executed four actual-function tests with UBSan.
- On each compiler, both production and readable pre-fix predicates reproduced
  the false match; both fixed predicates rejected it.
- Fixtures cover IPv4/IPv6, TCP/UDP, both cross-family directions, source and
  destination address/port differences, IPv6 trailing address words, empty-slot
  reuse, different empty-slot hashes and unsupported address families.
- Eight existing GCC lifecycle/control tests passed, including SHS failure
  paths and offload descriptor draining.
- Total: 16 successful test executions (12 distinct tests); no test was skipped.
  The duplicate legacy-test step is intentionally not run in the Clang job.

The fixtures compile extracted real predicates with the source header
declarations. They do not emulate the full packet path, kernel synchronization,
target ARM64 ABI or hardware networking.

## Remaining work

R46 has no new Image, linked ARM64 rmnet_offload.ko or flash package.
Host regression is not a substitute for a complete kernel/module build.
Rebuild native modules against the matching core before integrating this
source change into a ROM.

The three native RMNET runtime-removal qualification rows from R44 remain
blocked. Production SELinux/vendor/ROM integration and target networking
validation remain open. The retained-OEM trial image is unchanged.
