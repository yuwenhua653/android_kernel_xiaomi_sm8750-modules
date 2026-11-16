# R14: native module loading dependencies and partition staging

R13 proved the hard-symbol graph, not the actual loader graph. Its 14 network
roots had 69 modules in their hard dependency closure. Reading the compiled
ELF `softdep` records exposed three unresolved legacy names:

* IPA requested `subsys-pil-tz` and `qcom-arm-smmu-mod`, while this SUN tree
  builds `qcom_q6v5_pas` and `arm_smmu`.
* DWC3 requested `phy-msm-snps-hs`, which is not enabled. Annibale's
  `eusb2_phy0` instead uses `qcom,usb-m31-eusb2-phy`, and its USB overlay also
  uses the no-op PHY. The kernel builds both M31 and Synopsys eUSB2 providers.

These are loading declarations, not new hardware support or evidence that the
R13 kernel actually failed on a phone. Hard CRC validation cannot detect them.

## Driver fixes

The paired kernel's `drivers/usb/dwc3/dwc3-msm-core.c` now emits individual
soft dependencies for configured PHY drivers and QCOM EUD. Legacy HS and QUSB
providers remain supported when selected; disabled providers are not named.
This follows the actual USB PHY Makefile, rather than selecting a driver merely
because its `.c` file exists. Both configured eUSB2 alternatives are represented;
that does not claim that both chips are physically populated.

IPA's `ipa_v3/ipa.c` selects the actual PAS and ARM SMMU names for SUN, conditional
on their configuration. The pre-existing declarations remain on other platforms.
No fake aliases, CRC patches, warning suppression or symbol stubs are introduced.

The same qualification configuration was rebuilt, including Image, all 411
kernel modules and all 88 external modules. Exact results, hashes and the final
partition counts are in [annibale-r14-validation.json](annibale-r14-validation.json).
This changes the compiled kernel release; R13 external modules must not be
substituted for this build's outputs just because their filenames match.

## Explicit normal-boot network policy

[annibale-network-partitions.json](annibale-network-partitions.json) is a finite,
reviewable **source-only network subset**, not the complete device module list.
Partition ownership is explicit. Existing normal OS4 load-list placements are
used as reference evidence and checked against this source graph. The source
`qcom_pdr_msg` provider is explicitly placed with the late PDR/QMI stack.
No source-tree directory heuristic, stock module replacement, recovery module,
or automatic promotion into the early ramdisk is allowed.

One board dependency is also explicit: `phy_msm_m31_eusb2` needs
`repeater_qti_pmic_eusb2`. Annibale's `annibale-mtp.dtsi` connects `eusb2_phy0`
through `usb-repeater` to `pmih010x_eusb2_repeater`, and the PHY driver consumes
that phandle. Symbol dependencies alone only name the repeater framework and
cannot establish the concrete provider. This is not a complete DT supplier walk:
clocks, regulators, firmware readiness and other runtime probe relationships
still need the full device policy and hardware tests.

`tools/plan_annibale_modules.py` performs a fresh same-build check, verifies the
snapshotted `modules.builtin`, then resolves hard dependencies, every ELF
`softdep` pre/post clause and the reviewed board dependencies. It rejects missing
providers, mixed source/stock ownership, duplicate normalized names, dependency
cycles, incomplete ownership and load-stage inversions. Its stage model is
vendor_boot first, then system_dlkm, then vendor_dlkm; a real Android init setup
must establish those mount/load conditions before this plan can be used.

```sh
python3 -B tools/plan_annibale_modules.py \
  --kernel-out /path/to/out/annibale-btf \
  --module-stage /path/to/out/annibale-network/modules-XXXXX \
  --policy Documentation/xiaomi/annibale-network-partitions.json \
  --report /path/to/partition-plan.json \
  --stage /path/to/new-network-partition-check
```

The optional stage copies verified bytes into the three partition directories,
checks hashes before and after copying, and writes a SHA256 manifest. Existing
output directories are refused. Lists are deliberately named
`modules.load.candidate`: they are graph-derived candidates, **not installed
Android modules.load files**. No modules.dep/alias indexes, boot images or Android
BoardConfig integration are fabricated. Generate indexes through the selected
Android build after completing its module inventory and mount/loader policy.
Only firmware declared in ELF metadata is reported; runtime firmware requests
and calibration remain outside this check.

The existing `xiaomi-annibale/android_device_xiaomi_annibale` reference at
`1ed1eccfa3f68e1ec440b7f5e87ac97dc89475fe` still uses a prebuilt kernel and stock
module directories in BoardConfig.mk. This round does not claim to have converted
that separate repository to source compilation or Android 17.

## HyperOS and remaining hardware gaps

The exact OS4.0.6.0.XPKCNXM inventory is rechecked independently against the new
kernel. Stock providers stay together; the native policy must not be used to
replace the HyperOS module partitions. The inventory still has the R11 normal /
recovery and zram/zsmalloc ambiguities. Neither path is boot-qualified.

Audio review found both `si,sia91xx-i2c` nodes at 0x6e/0x6c and `tfa,tfa98xx`
nodes at 0x36/0x34 in the exact stock DTBO's audio I2C fragment. This identifies
candidate variants, **not the chip populated on the user's phone**. MiCode's
Annibale audio source at `9147f89e4e5814fe172f0f5cd3b774642c27c282` contains
smartpa registration and secondary-TDM routing that the LOS baseline lacks.
The current source DT composition still lacks Annibale audio wiring. No codec
is enabled from module-list presence alone in this round.

Next hardware work remains the audio variant/DT/machine-driver chain, Xiaomi
display and camera interfaces, and full charging policy. Full native module
coverage and partition/init integration remain prerequisites for a flashable
build; the network staging result is not a completion percentage.
