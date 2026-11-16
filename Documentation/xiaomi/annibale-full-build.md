Current firmware target and required checks for both ROM paths: [R11](annibale-rom-paths.md).

Current BTF prerequisites and stock-module checks: [R10 HyperOS ABI work](annibale-hyperos.md).

# R8 external module link qualification

The earlier touch/CSIPHY checks stopped at relocatable objects. R8 adds a fresh
staging build for the touch, camera, display, audio, DSP and NFC modules and their
real providers, followed by strict modpost against a complete matching kernel.
This validates the selected LOS module baseline and existing Annibale deltas;
it does not add all Xiaomi runtime extensions to those baseline drivers.

## Integration changes

- `msm_ext_display/Kbuild` used `$(srctree)/$(src)/include`. With absolute external
  source paths this incorrectly appended an absolute staging path to the kernel
  source path and failed to find `msm_ext_display.h`. It now uses the already
  required `MSM_EXT_DISPLAY_ROOT` consistently with the shared configuration.
- SYNX's `ipclite_test` module now honors `CONFIG_DISABLE_TEST_MODULES=y`, like
  the securemsm tests. The default when this flag is absent remains unchanged.
- `tools/build_annibale_modules.py` supplies the real source-root variables,
  stages all dependency providers, and uses one aggregate Kbuild/modpost. This
  allows SYNX and hardware-fence to resolve their mutual exports. It does not
  invent or suppress symbols and does not modify the kernel configuration.

The source groups are `mm-drivers/{msm_ext_display,hw_fence,sync_fence}`,
`mmrm-driver`, `synx-kernel`, `securemsm-kernel`, `display-drivers`, `audio-kernel`,
`camera-kernel`, `dsp-kernel`, `nxp/opensource/driver` and `xiaomi/touch/annibale`.
This is not the whole external-module repository: WLAN, Bluetooth, video,
data/IPA and remaining drivers still require their own complete integration.

Annibale's published NFC node is `qcom,sn-nci` at 0x28, with IRQ GPIO 75,
VEN GPIO 34 and CLKREQ GPIO 35. The existing NXP driver has this compatible;
its compilation/linking is included, without changing board wiring or claiming
that NFC or the secure element works on a device.

## Reproduction

First run `scripts/xiaomi/compile-annibale-board.sh full` or the explicit
experimental `qualify` profile in the kernel repository. The latter adds P11
fingerprint and MCA and disables the conflicting QTI battery client. It is not
a deployment configuration. Do not reconfigure that kernel output concurrently.

```sh
python3 -B tools/build_annibale_modules.py \
  --kernel /path/to/kernel/xiaomi/sm8750 \
  --kernel-out /path/to/out/annibale-qualify \
  --clang-bin /path/to/clang-r510928/bin \
  --output /path/to/out/annibale-external --jobs 6
```

The helper requires nonempty complete kernel inputs including Image, vmlinux,
Module.symvers and modules.order. It rejects environment options that bypass
modpost or inject mixed/extra symbol tables. `--objects` is an explicit limited
mode without final modpost; its result must not be called a loadable module.

To retry without recompiling unchanged sources, add `--resume-stage` pointing to
the reported staging directory under the same `--output`. It refuses changed
source hashes or modified staged source files; those require a fresh stage.
Kbuild handles changed kernel inputs, and the verifier checks the final result.

Each staging directory contains `build.log`, `build.json` (commands, source and
input hashes, return status, module hashes) and, on full verified success,
`verification.json`. The source revision and dirty state are recorded. Source
hashes identify the actual staged files even when validating uncommitted changes.
The build does not install modules, alter a ROM's loading lists, or flash devices.

`verify_annibale_modules.py` independently checks ordered kernel and external
modules for ELF64/AArch64, same release and vermagic flags, imported symbol CRCs
and module dependency presence. Missing ordered modules, wrong architecture,
truncated ELF tables, wrong release, CRC mismatches and missing dependencies
must fail. Existing unlisted `.ko` files in a reused kernel output are ignored.

```sh
python3 -B tools/verify_annibale_modules.py \
  --kernel-out /path/to/out/annibale-qualify \
  --module-stage /path/to/out/annibale-external/modules-XXXXX \
  --report /path/to/verification.json
python3 -B -m unittest discover -s tools/tests -v
```

The 14 host tests include the previous touch helper tests and nine new negative/
positive ELF/version/dependency cases. Actual artifact results are recorded in
`annibale-r8-validation.json`. Existing securemsm deprecated-header diagnostics
and inherited duplicate kernel DT target recipes are not hidden. The completed
run linked 58 external modules against 410 qualification kernel modules; all
468 ordered modules passed the ELF, version, CRC and dependency checks.

## Limits

Passing modpost and same-build CRC checks is not proof of compatibility with
stock prebuilt modules, Android KMI allowlists, trusted module signatures, CFI
execution, live HAL interfaces or hardware. The experimental touch port remains
an unverified same-family candidate. Xiaomi display extensions, K90 amplifier
selection/routing, camera extensions and charging policy remain unfinished.
Firmware and TEE components are not supplied by this build. No flashable image
or final vendor/system_dlkm loading policy is produced.
