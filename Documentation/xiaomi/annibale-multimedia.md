# R22: camera, video, EVA and Bluetooth transport integration

This round fills a **runtime selection/DT integration** gap. `camera`,
`msm_video`, `msm_eva` and `btfm_slim_codec` were already part of the external
build, but the R18 interactive native plan did not select them. No new standalone
C driver is imported. One existing video loading declaration is corrected. The two new opt-in policies extend the interactive plan:

- `annibale-multimedia-tfa-partitions.json`
- `annibale-multimedia-sia-partitions.json`

The resolver still selects one source provider per name, traverses real ELF
hard/soft dependencies, verifies exact ownership and rejects load-stage
inversions. Additional reviewed OF edges order camera/CAMBIST clocks, video/EVA
clocks and GDSCs, SMMU, RPMh supplies, interconnects and pinctrl. Bluetooth SLIM
codec selection orders the NGD controller, its BAM DMA provider, common BT codec and power provider.
No FM radio or generic USB/network module is added just to match an OEM count.
Final WLAN/BT board power/pinctrl composition remains unresolved. In the current
composed source DT, slim_msm is disabled. Selecting its modules alone does not
enable the transport; do not claim Bluetooth SLIM probing is complete.

TFA and SIA remain separate candidates. The working OEM capture contains both
module families; being loaded does not identify which amplifier is physically
active. Do not concatenate the policies, select hardware from module names
alone, or transplant these lists into HyperOS.

## Video loader correction

The first real R22 dependency traversal rejected `msm_video` because its ELF
softdep still requested the nonexistent legacy `subsys-pil-tz`. SUN's
`firmware.c` directly calls `qcom_mdt_load`, `qcom_scm_pas_auth_and_reset` and
`qcom_scm_pas_shutdown`; the actual compiled hard dependencies already select
`mdt_loader` and `qcom_scm`. SUN now omits the obsolete PIL name and retains
`msm-mmrm`. Other platforms retain both original prerequisites. No fake alias,
provider stub, ignored softdep or CRC patch is used. A fresh strict external
build and real partition traversal are required after this C source change.

## Matching multimedia DT

The devicetrees repository adds `annibale-multimedia-v1-test.dts` and
`annibale-multimedia-v2-test.dts`. They reuse the existing sun video/EVA bindings,
select the correct video compatible/EVA revision, and retain Annibale board
`0x40008` and Xiaomi board `0xB`. DTBO root properties select an overlay; they do
not by themselves update a composed tree. A root fragment also restores the
Annibale identity in the merged candidate. Firmware carveouts are not moved.

Kbuild requires explicit `ANNIBALE_MULTIMEDIA_REV=v1` or `v2`, SUN and non-VM.
Default builds do not silently enable these test overlays. The standalone
validator chooses the revision from each of eight SUN base candidates and
checks both audio families and default/native display. It rechecks the earlier
interactive bindings, including camera nodes, after composition.

```sh
python3 -B tools/validate_annibale_multimedia.py \
  --kernel /path/to/kernel --modules /path/to/modules \
  --dtc /path/to/dtc --fdtoverlay /path/to/fdtoverlay \
  --output /path/to/new-dt-validation
```

This command is run from the devicetrees repository. `--interactive-input` can
reuse a complete 32-row interactive report: each DT hash is checked and the
interactive binding checks are rerun after composition. It does not establish
that an arbitrary supplied report was built from the current source checkout.
The R22 result reuses interactive output built in this same run.

## Native staging

After the complete kernel `qualify` and external `audio` builds documented in
`annibale-full-build.md`, use the existing real Android stager with one new
policy. It derives load lists and depmod indexes from verified ELF files and
keeps the native loader's system-before-vendor ownership contract.

```sh
python3 -B tools/stage_annibale_android.py \
  --kernel-out /path/to/kernel-out --module-stage /path/to/modules-STAGE \
  --policy Documentation/xiaomi/annibale-multimedia-tfa-partitions.json \
  --output /path/to/new-stage --depmod /path/to/depmod \
  --strip /path/to/llvm-strip
```

This is a partial source qualification stage, not final boot/vendor_boot/DTBO/
DLKM images. It does not provide proprietary firmware/calibration or a complete
ROM device tree. When `--odm-root` is omitted, existing ODM audio asset checks
are not performed; do not claim those assets were validated.

## HyperOS and hardware limits

The working OS4.0.6.0 capture closes the running-version and F2FS observation
questions, not OSS runtime compatibility. Retain the exact OEM module/firmware/
DT/ramdisk set in the separate retained-stock kernel experiment. A native
source plan passing does not make its individual modules safe to mix with OEM
binaries. R22 does not alter the OEM loading services or the R21 pinned boot
candidate builder.

Still open: first OSS boot; complete ROM image assembly/selection; GKI security,
signatures and runtime CFI; firmware/HAL/ioctl behavior; final WLAN/BT board
wiring; camera streaming/recording and EVA operation; Xiaomi display features;
full charging policy; suspend/wake and standby. Source staging and DT checks
are necessary evidence, not proof that these functions work on hardware.

## R22 result

The fresh full kernel build linked Image and 411 in-tree modules. The corrected
external `audio` profile linked all 91 modules with strict modpost, then passed
same-build CRC/ARM64/vermagic checks. The configuration and Module.symvers match
the earlier baseline exactly; the rebuilt Image/release differ and must not be
substituted for the R21 builder's pinned Image without a separate review.

Both native stages passed real depmod, stripping/BTF and index/load checks:
TFA selects 199 modules (66 early, 1 system, 132 vendor); SIA selects 200 (66,
1, 133). Each adds 13 providers to the corresponding R18 interactive plan.
Five missing-supplier cases plus an early-camera load inversion were rejected
for each family. All 99 host tests passed, including SUN/legacy video softdeps.
DT validation passed 32 multimedia compositions, 128 malformed/disabled-provider
mutations and eight selector cases. Exact hashes are in
`annibale-r22-validation.json`. No phone was flashed or boot-tested this round.
