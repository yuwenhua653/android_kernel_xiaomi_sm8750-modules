# R16: Annibale audio runtime prerequisites

R15 compiled the two amplifier candidates and bound their real ASoC DAIs.
R16 adds the missing discrete microphone enable control, the Xiaomi smartpa
type read ABI, and separate source partition plans for each amplifier family.
This remains opt-in source audio qualification, not a working-audio claim.

## Driver changes

`sun-annibale-dmic.c` consumes `qcom,cdc-dmic-enable-gpios` only on cards with
the explicit Annibale smartpa property. The corresponding R16 DT candidates
carry GPIO 183/182 and the exact stock active/sleep electrical settings.
Disabled or malformed nodes are rejected. A pinctrl supplier which has not
probed causes deferred probe. Active-state errors propagate; successful
activation has device-managed sleep/reference cleanup on probe failure or
unbind. Pins remain active while the card is bound, matching Xiaomi's published
Annibale policy. This is **not** new per-stream power gating or a standby fix.

`sun-annibale-sysfs.c` creates `/sys/kernel/smartpa/smartpa_type` after the
source sound card registers. The value is `tfa98xx` or `sia91xx`, derived from
the two already-bound, same-family codec providers. The file is read-only;
there is no write operation to pretend another chip is fitted. Existing
namespace ownership is an error. Failed registration and unbind release the
kobject. The Xiaomi global first-probe registry remains absent.

The common codec pinctrl lookup now balances the platform-device reference it
obtains. The sound-card error path leaves its private allocation to devres so
registered-card cleanup runs before private data is freed. This does not
constitute a complete upstream hot-unplug, SSR or asynchronous-firmware audit.

## Source partition candidates

Use `annibale-audio-tfa-partitions.json` or
`annibale-audio-sia-partitions.json`, never their union. Each extends the R14
network plan and assigns every selected module to one normal-boot partition.
The R16 planner checks explicit family selection, required SIA tuning, no
opposite-family module in transitive dependencies, and codec-before-machine
ordering. Reviewed OF dependencies add amplifier I2C/TLMM, common audio codec,
DMIC/LPASS and DSP-startup providers that ELF imports alone cannot describe.

```sh
python3 -B sm8750-modules/tools/plan_annibale_modules.py \
  --kernel-out out/annibale-btf \
  --module-stage out/annibale-modules-r16/MODULE_STAGE \
  --policy sm8750-modules/Documentation/xiaomi/annibale-audio-tfa-partitions.json \
  --report out/tfa-plan.json --stage out/tfa-partitions
```

Replace MODULE_STAGE with the completed build stage. The output contains
verified copies and `modules.load.candidate`, not final Android load files.
The I2C and microphone controllers can still defer during device probing;
module insertion order is not proof of hardware readiness. Complete Android
init/mount sequencing, depmod, signatures, firmware search paths, vendor HALs,
all-device coverage and final boot image assembly remain separate work.

HyperOS retains its coherent stock audio/DT/firmware family. Neither candidate
is a drop-in replacement for its stock machine driver. R16's combined audit
keeps the unresolved stock partition/recovery variant ambiguities visible.

## Exact OS4 assets

The supplied OS4 ODM partition was extracted with payload-operation and complete
partition SHA256 checks. Its hash is
`d03f12309b7a5bb11b1e2acc5e3a30978dfe0f49374c878c4d3f901f4755702b`.
This is integrity against the OTA manifest, not an OTA-signature trust check.
The unrelated OS3.0.8.0 global blob list in the reference ROM is not used as
proof of OS4 contents.

`annibale-os4-audio-assets.json` pins the actual firmware, selected ACDB,
amplifier init file and four mixer/resource XML files. It contains metadata,
not the proprietary files. `check_annibale_audio_assets.py` checks those hashes,
TFA container/SIA firmware header CRCs and bounds, selected mixer control names,
and the 48 kHz/32-bit secondary-TDM speaker, handset and VI-feedback contracts:

```sh
python3 -B sm8750-modules/tools/check_annibale_audio_assets.py \
  --odm-root /path/to/extracted/odm --variant tfa --report out/tfa-assets.json
```

Use `--variant sia` for the other family. The TFA container declares two
devices/seven profiles and version `3_01`; SIA firmware is version `1.0.5`
with channels 0/1 enabled. These checks do not interpret every register or DSP
instruction. XML control references agree with the imported source control
names and SIA's DT prefixes; live ALSA enumeration remains unverified. No
inference that a specific family is fitted is made from both files being present.
The sysfs read interface is restored from Xiaomi source; the exact OS4 userspace
reader and SELinux access to it are not established by this asset check.

The init files refer to per-device files under `/mnt/vendor/persist/audio`.
Do not replace these with another device's calibration or manufacture values.
Remaining work includes native firmware lookup/partition installation, the
complete DSP/ACDB topology, actual HAL loading/selection and SELinux, followed
by hardware audio and protection testing. Stock asset identity alone does not
prove the rebuilt kernel/audio ABI works with the stock HAL.

R16 results: 91 external + 411 kernel modules pass same-build checks; 69 host
and tool tests pass. The TFA plan selects 122 modules (32 vendor_boot, 1
system_dlkm, 89 vendor_dlkm); SIA selects 123 (32/1/90). Both families pass
16 total DT compositions and the selected exact-asset checks. The full stock
audit still reports eight unresolved variants and zero detected ABI blockers.

Validation and exact output hashes are in `annibale-r16-validation.json`.
Host tests execute the real DMIC and sysfs helper C files with mocked kernel
APIs, including provider deferral, pinctrl failure, namespace collision,
allocation/action failures and cleanup. They cannot prove pin voltage, sound,
recording, calibration/protection, HAL readiness or runtime power consumption.
