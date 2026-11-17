# R28: secure processor and vendor policy integration

The native build previously omitted the existing Qualcomm `spu-kernel` sources.
R28 adds that group to the unified platform/network/audio build, checks its
kernel provider configuration before compiling, and requires both `spcom.ko`
and `spss_utils.ko` in post-link verification. The original driver UAPI and DT
firmware selection remain unchanged.

A concrete probe error-path fix moves `rproc_put()` immediately after
`qcom_spss_set_fw_name()`: failed firmware-name allocation must also release the
reference acquired by `rproc_get_by_phandle()`. The compiled host test exercises
the actual probe prefix with successful, failed and deferred providers. It does
not exercise the later chardev setup or claim a hardware test.

## Load and DT contract

New native policies `annibale-spu-{tfa,sia}-partitions.json` extend R27. All four
new selections live in vendor_dlkm, alongside the existing remoteproc/GLINK
providers:

| Driver | Integration role |
| --- | --- |
| qcom_glink_spss | SPSS transport with IPCC supplier ordering |
| qcom_spss | Sun remoteproc, AOSS, RPMh clock/regulators and interconnect |
| spss_utils | Fuse-dependent firmware selection before communication devices |
| spcom | Secure processor userspace communication after the reviewed providers |

`qcom_spss` and `qcom_glink_spss` reuse matching R22 kernel modules. `spcom` and
`spss_utils` are newly compiled with the entire external module set in one strict
modpost. Ordering is an insertion contract, not proof of successful probes or
userspace readiness. No HAL is forced to start and no secure firmware is loaded
on a physical device by these tools.

The scoped DT checker examines all 32 final base/overlay combinations. Both
SPU clients must point to the same active Sun remoteproc and the same reserved
no-map memory. It validates memory capacity, typed supplier arguments, GLINK
mailbox/interrupt linkage, the control channels and the existing three firmware
names (`spss1d.mdt`, `spss1t.mdt`, `spss1p.mdt`). Firmware bytes, signatures and
runtime selection are not qualified by this check.

## Vendor policy path correction

The pinned reference BoardConfig included `device/qcom/sepolicy_vndr/SEPolicy.mk`,
while the reviewed CAF branch internally sets
`SEPOLICY_PATH := device/qcom/sepolicy_vndr/sm8750`. The conversion patch now
includes `device/qcom/sepolicy_vndr/sm8750/SEPolicy.mk` explicitly. Sync the CAF
repository to that same directory; do not flatten it into the parent.

The validation checkout mounts the real policy repository there and evaluates
its vendor directory list with GNU Make. This checks that the `generic` and
`qva` Sun policy directories resolve; it is not a compiled combined SELinux
policy. Existing qva contexts label `/dev/spss_utils`, `/dev/sp_kernel` and
`/dev/sp_ssr`; generic contexts label `/dev/spcom`. The reference device ueventd
already assigns these four nodes mode 0660 and system:system. No permissive
policy or broad allow rule is added.

Reference: [LineageOS CAF policy at 490d47f](https://github.com/LineageOS/android_device_qcom_sepolicy_vndr/tree/490d47fb8438a2ecd99c1338472f80561572c362).

## Reproduce

```sh
python3 -B sm8750-modules/tools/build_annibale_modules.py \
  --kernel sm8750 --kernel-out out/annibale-btf-r22 \
  --clang-bin tools/clang-r510928/bin \
  --kernel-tools-bin tools/kernel-build-tools/linux-x86/bin \
  --output out/annibale-modules-r28 --jobs 6 --profile audio

python3 -B sm8750-modules/tools/check_annibale_spu_dt.py \
  --devicetrees sm8750-devicetrees --dt-images out/annibale-r24-dt-images \
  --report out/annibale-r28-spu-dt.json
```

Use the new build's printed stage with `stage_annibale_android.py` and the SPU
policy for each family. Recreate the fragment, native images and ROM handoff
with the existing tools, as described in [R27](annibale-power.md). Earlier stages
and their hashes remain historical records, not the expanded R28 selection.

## Recorded results

- Fresh unified build: 93 external modules, checked against 411 kernel modules.
- TFA plan: 217 modules (78 early, 1 system, 138 vendor).
- SIA plan: 218 modules (78 early, 1 system, 139 vendor).
- Both native image sets and ROM handoffs passed offline content checks.
- 163 tests passed; 32 final DTBs passed the scoped SPSS checks.
- All 9440 recorded source files still match the compilation snapshot.

## Qualification boundary

See `annibale-r28-validation.json` for actual build/test/image results. Kernel
Image and final DTBs are reused; external modules are rebuilt. Neither a full
ROM/init_boot build nor hardware boot, secure services, firmware loading,
SELinux enforcement or suspend has been verified. The matching generated vendor
tree is still absent. These remain **qualification artifacts, not a flash package**.
