# R27: native power and thermal driver integration

The R23 wireless plans omitted power/thermal modules even though the R22
qualification build produced them and the final Sun DTBs enable their nodes.
R27 adds 13 source-built modules to each native plan. It does not rebuild the
kernel or change retained-stock HyperOS module ownership.

| Modules | Purpose | Partition |
| --- | --- | --- |
| qcom_cpufreq_thermal, qti_cpufreq_cdev, thermal_pause | CPUCP temperature throttling, CPU cooling and thermal pause | vendor_boot |
| qcom_lpm | Three PSCI cluster low-power devices | vendor_boot |
| qti_ocp_notifier | 69 regulator supplies and two SDAM log cells | vendor_boot |
| qcom_tsens, qti_thermal_vendor_hooks | Four TSENS blocks and thermal registration/suspend hooks | vendor_boot |
| qcom_spmi_adc5_gen3, qcom_vadc_common, qcom_spmi_temp_alarm | ADC conversion and twelve active PMIC temperature alarm nodes | vendor_boot |
| qcom_stats | RPMh sleep statistics through AOSS | vendor_boot |
| ddr_cdev | DDR thermal bandwidth limit through Sun interconnect | vendor_boot |
| qti_devfreq_cdev | GPU devfreq cooling after msm_kgsl insertion | vendor_dlkm |

The CPU performance driver is already **built-in SCMI**, with CPU clocks using
protocol 0x13 and two performance domains. Stock modules.load also lists
qcom-cpufreq-hw, but the reviewed Sun trees do not need that driver as a
replacement for SCMI. Built-in SCMI/PSCI configuration is checked explicitly.
Insertion ordering is necessary but does not prove provider probe completion.

New policy entry points:

- `annibale-power-tfa-partitions.json`: 213 modules = 78 early + 1 system + 134 vendor.
- `annibale-power-sia-partitions.json`: 214 modules = 78 early + 1 system + 135 vendor.

Both extend the R23 wireless/audio plans. Historical policy files remain intact
so their validation hashes still identify the earlier stages. The power profile
requires all reviewed drivers and explicit runtime ordering edges; an ELF-only
dependency walk is insufficient for mailboxes, regulators and cooling devices.
The existing planner also checks exact ownership, dependency closure, cycles
and partition stage inversions.

## Reproduce

Use the R22 kernel build `c70ed7c690cc908451daf53c14afa8d3ceb20ca9`, its matching
module stage and R24 merged DT output. From the three-repository workspace:

```sh
python3 -B sm8750-modules/tools/check_annibale_power_dt.py \
  --devicetrees sm8750-devicetrees --dt-images out/annibale-r24-dt-images \
  --report out/annibale-r27-power-dt.json

python3 -B sm8750-modules/tools/stage_annibale_android.py \
  --kernel-out out/annibale-btf-r22 \
  --module-stage out/annibale-modules-r22-fixed/modules-s_fcu1ye \
  --policy sm8750-modules/Documentation/xiaomi/annibale-power-tfa-partitions.json \
  --depmod tools/kernel-build-tools/linux-x86/bin/depmod \
  --strip tools/clang-r510928/bin/llvm-strip \
  --output out/annibale-r27-android-tfa
```

Repeat staging with the SIA policy and a separate output. Use the existing
`prepare_annibale_ramdisk_fragment.py`, `build_annibale_native_images.py` and
`prepare_annibale_rom_handoff.py` with these new stages/policies; do not reuse an
R24 fragment or R25/R26 handoff with the expanded plan. See
[ramdisk integration](annibale-ramdisk-integration.md),
[native images](annibale-native-images.md) and [ROM handoff](annibale-rom-handoff.md).

## Evidence and remaining gaps

- 32 final DTBs: active node counts, typed phandle arguments, enabled supplier
  ancestry and CPU SCMI clock protocol checked. This is a scoped static audit,
  not a complete fw_devlink graph or thermal-policy validation.
- Both stages rechecked from actual ELF modules: 213/214 installed modules.
- Both 78-module fragments roundtrip-checked; vendor_boot contains platform and
  DLKM fragments. EROFS contents, mode/ownership/SELinux labels and extraction
  checked for both families.
- Both ROM handoffs applied to the pinned reference device tree in an isolated
  checkout; GNU Make include evaluation and 1003 header exports passed. This is
  not an Android Kati/Soong build.
- 151 tests passed, including ten new power-profile/DT negative tests.

No fresh kernel compilation, CI build, phone flash or hardware result is claimed.
Full ROM evaluation still lacks `vendor/xiaomi/annibale/BoardConfigVendor.mk` and
matching generated vendor files. Android 17/HyperOS 4 HAL/firmware compatibility,
secure processor coverage, final init_boot/AVB ownership, enforcing SELinux,
thermal policy, suspend residency and actual probe completion remain unverified.
The generated images and handoffs are qualification artifacts, **not a flash package**.
