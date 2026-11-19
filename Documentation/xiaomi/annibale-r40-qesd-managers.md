# R40: complete the seven-file QESD manager supplement

R40 supplies **all seven remaining R39 source inputs together**: two manager
executables, two init files, two seccomp policies and one device VINTF fragment.
It also repairs specific missing syscalls in both policies. The seven-item
source-input remainder is now **zero**; this is not a count of working drivers
or a claim that the whole OSS port is complete. The full firmware inventory
has not been repeated against a complete reconstructed dump.

R38's eSIM supplement and R39's privileged, platform-signed QESD system APK
remain required. The Linux 6.6 kernel and HyperOS retained-stock route are not
changed by this native-ROM extraction supplement. Do not copy these binaries
or the APK directly into a running stock HyperOS installation.

## What changed

| Input | Integration |
| --- | --- |
| `vendor/bin/qesdk-manager` | Pinned ARM64 executable, unchanged bytes |
| `vendor/bin/qesdk-secmanager` | Pinned ARM64 executable, unchanged bytes |
| Two `vendor/etc/init/qesdk*.rc` files | Original system UID, class hal and named sockets retained |
| `vendor/etc/seccomp_policy/qesdk.policy` | Add `sendto` |
| `vendor/etc/seccomp_policy/qesdksec.policy` | Add `sendto`, `lseek`, `exit`, `exit_group`, `rt_sigreturn`, `restart_syscall` |
| `vendor/etc/vintf/manifest/qesdk-manager.xml` | One AIDL V2 `vendor.qti.qesdhalaidl.IQesdhal/default` device instance |

The source is [SM8750-AB/vendor_xiaomi_annibale at 5d498c3f](https://github.com/SM8750-AB/vendor_xiaomi_annibale/tree/5d498c3ffd6260c6b9817aa417f4c44d639a2376).
Every input and prepared output has an exact SHA-256 in the
[profile](annibale-qesd-managers.json); the generated extraction entries pin
the final SHA-1, including the repaired policies. There is a separately
selectable `QESD manager supplement` section. The retained OS4 libraries and
R39 APK section are not extracted from this seven-file source.

### Seccomp evidence

The security manager calls `__sendto_chk` at ARM64 virtual addresses `0x99e8`,
`0xa190`, `0xa454`, `0xaa04`, `0xac5c`. Its startup enters `SetUpMinijail`
before starting the worker/socket path. The OS4 `libqesdk_manager.so` also
imports `sendto` and `__sendto_chk`. Bionic's `fortify.cpp` forwards the checked
call to `sendto`; `SYSCALLS.TXT` maps `__sendto` to the ARM64 `sendto` syscall.
Both donor allowlists denied that syscall. These are real socket-reply paths,
not reasons to disable seccomp.

The security manager and its Mink dependencies create threads; Mink imports
`pthread_exit` and `sigaction`. Bionic thread teardown reaches the `exit`
syscall; normal process exit uses `exit_group`, signal return uses
`rt_sigreturn`, and interrupted blocking operations may use `restart_syscall`.
Its binder/crypto/cutils dependencies import `lseek`. The security allowlist
omitted these lifecycle/file operations, while the manager policy already
allowed them. R40 brings those selected rules into the security policy.
This is a source/disassembly finding, not a captured device SIGSYS trace.

Both policies were compiled with pinned upstream Minijail for **ARM64**, not
the host syscall ABI. Simulation checks that each added syscall changes from
KILL_THREAD to ALLOW, UNIX sockets still pass, IPv4/IPv6 sockets still fail,
write+execute mappings still fail, and unknown syscalls/wrong architectures
still fail. Existing `nanosleep` remains allowed. The policy text still goes
through the device's Minijail at runtime; host compiler simulation does not
test that device parser or exercise the daemon on a phone.

Primary implementation references:

- [Bionic syscall definitions](https://github.com/LineageOS/android_bionic/blob/lineage-24.0/libc/SYSCALLS.TXT), Git blob `3622ca4f4509296a652327d90d12ab9569cd2b0c`.
- [Bionic checked calls](https://github.com/LineageOS/android_bionic/blob/lineage-24.0/libc/bionic/fortify.cpp), blob `a1cc4e8ada2ddd8bd8e397eb460bb5f97af1b4cc`.
- [Bionic thread exit](https://github.com/LineageOS/android_bionic/blob/lineage-24.0/libc/bionic/pthread_exit.cpp), blob `25d828acc86976df0682b185413cb6f737341a85`.
- [Minijail compiler](https://github.com/google/minijail/tree/c46d08600b8b6548809d37be1964396efde1c3ac).

### Libraries, startup and policy

Selected dependencies were recovered from the official OS4.0.6.0.XPKCNXM OTA,
including the runtime APEX's libc, libm, libdl and linker64. Compressed payload
operation SHA-256 values were checked before extraction. These are selected
files from partial working images, not newly verified complete partitions;
OTA signatures and whole-partition hashes were not reverified.

The offline dependency graph contains 44 distinct objects. The manager's
42-object closure checks 3,954 imports; the security manager's 35-object
closure checks 3,167 imports. Both have **zero unresolved strong imports**.
Unresolved weak symbols are listed in the report (21 and 18 respectively),
not treated as required providers. Versioned imports must match their version.

The graph separates system and vendor providers. A system `libbinder_ndk`
must use the system binder/C++ dependencies rather than accidentally matching
the vendor copies. Each object's imports are checked against its own
dependency closure; an unrelated export cannot hide a missing dependency.
This is an explicit offline scope model, not a check of the generated phone
linker configuration. It also does not prove hidden C++ layouts, CFI,
callbacks, dynamically loaded services or API behavior. A native ROM replaces
framework libraries and still needs its own build-time ELF checks.

The old V3 security client is kept with the existing OS4 V3 NDK library; the
OS4 manager library uses V4. Neither client is renamed or shimmed to another
version. R39's system-service APK implements V4. Successful runtime interaction
between those clients, the service and the secure-world component is pending.

The existing Qualcomm policy at
[19dd1d9a](https://github.com/LineageOS/android_device_qcom_sepolicy_vndr/tree/19dd1d9a3ce4ac8d993203edac1ec05749a8d60b)
already supplies executable transitions, QESD sockets, database labels, HAL
registration and the security-manager-to-ssgtzd socket connection. The tree
includes that policy. OS4 `ssgtzd.rc` explicitly starts `vendor.ssgtzd` and
creates the expected socket; both its binary and init file retain their own
extraction entries. No authentication code, provisioning behavior, permissions
or SELinux allow rules are bypassed or synthesized.

## Apply after R39

Obtain the seven donor files listed in the profile, keeping paths relative to
`proprietary/`, from the pinned donor commit. Supply the exact OS4 dump or the
recovered selected stock files, the reviewed Qualcomm vendor policy checkout,
and the R39-converted device tree:

```sh
python3 -B sm8750-modules/tools/prepare_annibale_qesd_managers.py \
  --donor /path/to/donor/proprietary \
  --stock /path/to/os406-dump \
  --qcom-policy /path/to/device/qcom/sepolicy_vndr/sm8750 \
  --device-tree /path/to/r39/device/xiaomi/annibale \
  --output out/new-annibale-qesd-managers
git -C /path/to/r39/device/xiaomi/annibale apply \
  /absolute/path/to/out/new-annibale-qesd-managers/annibale-qesd-managers.patch
```

After ordinary stock extraction and the R38/R39 supplements, add this section
without clearing the already extracted files:

```sh
device/xiaomi/annibale/extract-files.py \
  --section 'QESD manager supplement' --no-cleanup \
  /absolute/path/to/out/new-annibale-qesd-managers/source
```

The preparer checks exact input hashes, ownership, init/VINTF/policy contracts,
and rejects drift or reuse of an existing output directory. It does not modify
inputs. Downloading a donor tree alone does not apply the seccomp corrections:
use the **prepared** source directory and corresponding extraction-list patch.

For repeatable policy validation, provide the Minijail revision and ARM64
header Git blob documented by `verify_annibale_qesd_seccomp.py`:

```sh
python3 -B sm8750-modules/tools/verify_annibale_qesd_seccomp.py \
  --minijail /path/to/minijail \
  --arm64-header /path/to/asm-arm64/asm/unistd_64.h \
  --donor /path/to/donor/proprietary \
  --prepared-source out/new-annibale-qesd-managers/source \
  --output out/qesd-seccomp-validation.json
```

## Completed checks and remaining gates

**76 relevant unit tests passed**: 13 new manager/ELF regressions, 17 source
supplement tests and 46 OS4 migration tests. Real extract-utils at
`44e3b07397a339c2721c637e40cb73159c78ad46` extracted all seven pinned inputs in
one invocation, preserved an existing input and generated two ARM64 binaries,
four configuration copies and one `prebuilt_etc_xml` VINTF module. Each has
one destination owner. ELF checks remain enabled. The generated patch applies
cleanly to R39 and matches the preparer's final extraction list.

Still required before calling this usable:

1. Complete native ROM build, platform signing, generated linker configuration,
   SELinux compilation and assembled VINTF compatibility checks.
2. On-device QESD service startup, enforcing-mode labels, socket exchange,
   secure service responses and absence of SIGSYS/linker errors.
3. OSS 6.6 boot and hardware regression testing on both intended ROM routes.

No complete ROM or new flashable image was built, and there was no device
execution in this round. Remaining runtime gates must not be relabelled as
fixed hardware gaps merely because the seven source files are now supplied.

Evidence: [profile](annibale-qesd-managers.json),
[patch](patches/annibale-qesd-managers.patch),
[validation](annibale-r40-validation.json).
