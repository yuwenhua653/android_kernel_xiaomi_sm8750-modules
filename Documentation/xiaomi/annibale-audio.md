Latest: [R16 microphone enable, smartpa ABI and family-specific loading](annibale-audio-runtime.md).

# R15: opt-in Annibale smart amplifier source integration

This round adds real Xiaomi TFA98xx/TFA986x and SIA91xx codec sources, SIA
tuning support, and explicit secondary-TDM sound-card binding to the existing
LOS audio stack. These are **qualification candidates**, not boot-tested audio.
The existing media/platform/network profiles remain unchanged; select `audio`
to build the three additional modules:

* `tfa98xx_dlkm.ko`
* `sia91xx_dlkm.ko`
* `sia91xx_tuning_dlkm.ko`

Source: [MiCode Annibale audio release](https://github.com/MiCode/vendor_qcom_opensource_audio-kernel/tree/9147f89e4e5814fe172f0f5cd3b774642c27c282),
branch `annibale-w-oss`. The 90 imported C/header files, original and normalized
hashes, and adapted hashes are in `annibale-audio-source.json`. Existing license
notices are preserved. This does not replace the entire LOS audio stack with
the older Xiaomi tree. No firmware, calibration, stock binaries, keys or
proprietary userspace is included. Unbuilt upstream helper sources are retained
for context; the Kbuild object lists follow the published audio_modules.bzl.

## Integration changes

The Xiaomi first-probe global smartpa registry is not imported. Instead,
`sun-annibale.c` requires two distinct, available, same-family codec phandles
in `xiaomi,smartpa-codecs` and a TDM-capable card. Registered ASoC providers
supply the actual DAI names, including their dynamic I2C suffixes. The helper
changes the secondary TDM RX and TX links only after both providers are ready;
it preserves deferred-probe errors and leaves unrelated links alone.

Each provider requires `#sound-dai-cells = <0>` and the explicit boolean
`xiaomi,annibale-audio`. Both SIA platform and I2C nodes require that marker.
Without the sound-card property, machine binding takes the original LOS path.
Without the provider marker, these imported codecs refuse to probe. This gate
does not make simultaneous stock/source modules safe: a ROM must still assign
each module family to exactly one owner.

Local changes to the two codec entry points remove registry calls, propagate
GPIO request failures, defer SIA I2C probing until its platform provider exists,
release its parsed OF reference, and unwind platform registration if I2C
registration fails. TFA removal avoids cancelling work never initialized by
component probe and clears a destroyed workqueue pointer. This is not a full
audit of upstream asynchronous firmware loading, hot-unplug or driver unload.

## Build and validation

From the workspace containing the three sibling repositories:

```sh
python3 -B sm8750-modules/tools/build_annibale_modules.py \
  --profile audio --kernel sm8750 --kernel-out out/annibale-btf \
  --clang-bin tools/clang-selected/clang-r510928/bin \
  --kernel-tools-bin tools/kernel-build-tools/linux-x86/bin \
  --output out/annibale-modules-r15-final --jobs 9
python3 -B -m unittest discover -s sm8750-modules/tools/tests
```

Use the R14 matching kernel output (`6.6.144-4k-gf112270e61a8`), not an R10
Image. Exact input/output hashes and results are in `annibale-r15-validation.json`.
The host harness compiles the actual binding C file with stub OF/ASoC APIs and
checks absent/invalid configuration, missing/duplicate backends, mixed/disabled
providers, allocation/action failures, deferred probe on either codec, successful
retry, copied DAI names and OF-reference cleanup. It is not a hardware test.

R15 validation: 91 external + 411 kernel modules passed strict modpost and
same-build ARM64/vermagic/CRC/dependency checks; 57 host/tool tests passed.
Both opt-in DT families passed 16 selected-base compositions. The stock audit
found zero ABI blockers but remains `incomplete_inventory` for eight variant
ambiguities. Build warnings and upstream indentation warnings are recorded,
not suppressed. None of these results establishes boot or working audio.

## HyperOS and native paths

HyperOS OS4.0.6.0.XPKCNXM continues to use its original coherent audio module,
DT, DSP firmware and userspace family. This round does not replace those
modules or claim binary compatibility of the newly imported source drivers
with the stock machine driver. The exact-stock inventory remains subject to
the eight partition/recovery variant ambiguities described in R11/R14.

For a native ROM, use the source machine driver and exactly one matching codec
family with the corresponding opt-in DT candidate in the devicetree repository.
The stock DT contains both families; that alone does not identify the populated
hardware. The candidates reconstruct board wiring from the supplied OS4 DTBO,
not from a claimed MiCode audio DT release. Default DT builds select neither.

Still required before audio can be called functional: identify the populated
amplifiers, assemble the complete board DT chain and correct partition load
policy, integrate matching DSP firmware and TFA container or `sipa.bin`, audit
HAL/AGM mixer and route contracts, and validate speaker/receiver, microphones,
USB/Bluetooth audio, suspend/resume and error recovery on hardware. No boot,
sound output, protection/calibration, volume or thermal result is claimed.
