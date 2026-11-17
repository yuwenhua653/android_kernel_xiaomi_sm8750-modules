# R23: Annibale WLAN and Bluetooth board integration

R23 closes the selected WLAN/BT board-wiring and HS UART loading gaps left by
R22. It does not establish successful probe, firmware loading, Bluetooth audio,
Wi-Fi association, suspend or first OSS boot. Kernel C and external driver C
sources are unchanged; this round reuses and rechecks the R22 complete builds.
The native candidates remain partial, non-flashable source qualification.

## Evidence and board changes

The reference is the user's OS4.0.6.0.XPKCNXM full OTA for **annibale**, not a
K90 Pro Max tree or a third-party repacked kernel. The extracted vendor_boot
and dtbo partitions match all operation hashes and final partition hashes in
the payload manifest. OTA/payload cryptographic signatures were not verified.
Eight vendor_boot base DTBs merge with its single DTBO entry. Their selected
wireless contracts are identical; partition and DT hashes are recorded in the
companion devicetrees repository's `annibale-os406-wireless-contract.json`.
No stock firmware or complete stock image is added to either source repository.

The dedicated Annibale DTS includes are derived from the existing Qualcomm
Kiwi v8 sources, with these reviewed differences:

- BT_EN on PM8550VE_F GPIO3 and FMD clock GPIO6 use `power-source = <1>`,
  matching this board. The reference-board value was 2.
- Omit the reference-board RTC6226 FM device, absent in this OEM DT.
- Omit the generic WLAN XOCAL/WCAL consumer properties, absent in this OEM DT.
  Existing Bluetooth FMD NVMEM cells remain connected.
- Enable UART14 and the existing SLIM NGD node. Target `&slim_msm` rather than
  redefining its label/node, preserving the controller's original phandle.

The validator compares typed GPIO/clock/interconnect/supply references, numeric
arguments, pin groups, provider identity, serial aliases and the complete set
of enabled `qcom,msm-geni-serial-hs` nodes. A numeric GPIO or clock argument must
not be interpreted as a phandle merely because the values coincide. The only
normalized representation difference is PCIe root-port address/size cells:
LOS explicitly declares 3/2; OEM obtains the same values from its ancestor.

## Native module selection

Use `annibale-wireless-tfa-partitions.json` or
`annibale-wireless-sia-partitions.json`. Each extends its R22 multimedia policy
with **msm_geni_serial** in vendor_dlkm: the built-in `qcom_geni_serial` console
is not the matching high-speed UART driver. The reviewed UART uses the GENI
SE provider and internal DMA; no unrelated GPI DMA requirement is invented.
Explicit OF dependencies also order BT power's PMIC GPIO, RPMh supply/clock,
AOSS QMP and SDAM NVMEM providers, CNSS/PCIe providers, and SLIM's BAM DMA.
The `wireless_profile = annibale-kiwi` guard rejects incomplete transport
selection or lost reviewed BT/UART/SLIM ordering, even if a supplier happens to
be loaded for another consumer.

TFA selects 200 modules: 66 vendor_boot, 1 system_dlkm, 133 vendor_dlkm.
SIA selects 201: 66, 1, 134. The actual amplifier family remains unconfirmed;
the healthy OEM capture loads both families. Keep these source plans separate.
HyperOS retains its OEM DT/modules/firmware/ramdisk ownership and does not
consume these native policies. This round does not change its services or
qualify mixing source modules with OEM binaries.

From this modules repository, after the builds in `annibale-full-build.md`:

```sh
python3 -B tools/stage_annibale_android.py \
  --kernel-out /path/to/kernel-out --module-stage /path/to/modules-STAGE \
  --policy Documentation/xiaomi/annibale-wireless-tfa-partitions.json \
  --output /path/to/new-stage --depmod /path/to/depmod \
  --strip /path/to/llvm-strip
```

From the sibling devicetrees repository:

```sh
python3 -B tools/validate_annibale_wireless.py \
  --kernel /path/to/kernel --modules /path/to/modules \
  --dtc /path/to/dtc --fdtoverlay /path/to/fdtoverlay \
  --output /path/to/new-wireless-dt-validation
```

`--multimedia-input /path/to/r22-dt-validation` may reuse a complete 32-case
media matrix. All input DT hashes and prior interactive/media bindings are
checked, but an arbitrary supplied report is not proof of current-source
provenance. This round uses the retained R22 local build. The dedicated Kbuild
selector `ANNIBALE_WIRELESS_MODE=native` requires SUN and non-VM; empty leaves
the overlay unselected. It is an incremental test overlay applied after the
interactive and revision-specific multimedia composition, not a standalone
replacement for the OEM DTBO partition.

## Validation and remaining work

Both fresh Android stages pass real depmod, ELF CRC/vermagic, load ordering,
stripping/BTF invariants and output manifest checks. Six real-ELF negative
provider/order cases are rejected for each audio family. Source hashes,
symlinks, all 502 R22 module ELF hashes and pinned kernel inputs were rechecked;
this is not a new C compilation. Host suites pass 103 module-tool tests and
5 DT parser tests. The 32 merged DT candidates pass 224 deliberately broken
wireless cases and 7 Kbuild selector cases. Each checks 68 selected nodes and
52 referenced supplier entries and preserves preexisting camera/display/audio
properties, apart from the explicitly reviewed transport enables.

Still needed: complete native ROM image/DTBO selection and ramdisk integration;
first OSS boot; firmware/calibration/HAL contracts; Wi-Fi and BT probe/runtime;
BT SLIM audio routing; camera streaming; charging and display features; suspend
and standby. GKI policy, signatures and runtime CFI remain unqualified (the
experimental qualify build has an empty generated GKI unprotected list).
ODM audio asset checks were not rerun. No phone was flashed this round.
