# Annibale P11 CSIPHY import

This adds the Redmi K90 (`annibale` / P11) D-PHY variant to the existing
LineageOS SM8750 camera driver. The corresponding device-tree node is
`cam_csiphy2`, with compatible strings `qcom,csiphy-v2.3.0-p11` and
`qcom,csiphy`.

## Source and scope

- Source: `MiCode/vendor_qcom_opensource_camera-kernel`, `annibale-w-oss`.
- Source commit: `90523a7223f3ad562871414cd5997ece2d5a3c60`.
- Source files: `drivers/cam_sensor_module/cam_csiphy/cam_csiphy_soc.c` and
  `drivers/cam_sensor_module/cam_csiphy/include/cam_csiphy_2_3_0_hwreg.h`.
- The 103 register entries in `csiphy_2ph_v2_3_0_reg_p11` are copied without
  changing their values, order, delay or parameter type.
- The P11 compatible selects this table with hardware version V230 and the
  same divisor and clock-lane settings as the original Xiaomi implementation.
- Existing GPL-2.0-only SPDX and copyright notices are retained.

The public Xiaomi table declaration has SHA-256
`c917ab3e78b7fb79be5b6298566b7ede05f67ffda3798d9e45e2233af0a72500` when hashed
from its `struct` declaration through its terminating `};`, without a final
newline. This identifies the imported table, not the full file.

## Integration choices

The LineageOS shared register tables remain unchanged. In particular, its
separate 2-phase/3-phase common-register programming and newer reset delays
are retained. The common 3-phase, combo, interrupt, lane, data-rate and BIST
tables are reused. No O1/O11U variants or other Xiaomi camera changes are
imported by this patch.

A separate P11 register-parameter structure derives its D-PHY entry count
from the P11 array. This avoids relying on the generic D-PHY table having
the same number of entries after future upstream changes. Other parameters
match the current LineageOS V230 structure.

The existing `CONFIG_SPECTRA_SENSOR` path already builds `cam_csiphy_soc.o`;
no additional module, Kconfig switch or replacement Kbuild is required.
The P11-specific selection is evaluated before the generic V230 compatible.

## Validation boundary

Static checks confirm that the imported P11 table matches the pinned source
and all 16 existing shared declarations remain unchanged. On 2026-11-15,
`cam_csiphy_soc.o` compiled successfully with Android Clang r510928
(11368308, Clang 18) against the prepared Annibale kernel configuration.
The result was verified as an ELF64 AArch64 relocatable object containing
the P11 register, parameter and control tables. No compiler warnings were
reported for this target.

With the toolchain in `PATH` and the kernel output already configured and
prepared, the object check is:

```sh
make -C "$KERNEL_SRC" O="$KERNEL_OUT" ARCH=arm64 LLVM=1 LLVM_IAS=1 \
  M="$CAMERA_SRC" CAMERA_KERNEL_ROOT="$CAMERA_SRC" KERNEL_ROOT="$KERNEL_SRC" \
  MODNAME=camera -j1 drivers/cam_sensor_module/cam_csiphy/cam_csiphy_soc.o
```

`KERNEL_SRC`, `KERNEL_OUT` and `CAMERA_SRC` are absolute paths to the kernel,
its prepared output and this camera module tree. The check used an isolated
copy of the camera source so generated objects stayed outside the working
repository. The companion Annibale camera overlay is maintained in the
devicetrees repository.

Complete `camera.ko` linking, external-module symbol compatibility, camera
HAL integration and sensor streaming require separate validation. Importing
this PHY table does not establish that front/rear cameras work on hardware.
