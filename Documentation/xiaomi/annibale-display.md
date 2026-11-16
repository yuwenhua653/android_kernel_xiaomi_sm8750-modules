# R19: opt-in P11 PB panel quirks

The native source display driver can now apply two narrow P11 PB behaviors from
MiCode `vendor_opensource_display-drivers`, `annibale-w-oss`, commit
`4a586833e811c8ec53e6924116505b5724a90c2d`:

- Wait at least 5 ms before asserting the power-off GPIO sequence.
- On PB revisions below `0x80`, clamp nonzero DBV values below 15 to 15.

Reference locations are `msm/dsi/dsi_panel.c` (`dsi_panel_power_off` and
`dsi_panel_set_backlight`) and `msm/mi_disp/mi_dsi_display.c`
(`mi_dsi_display_read_panel_build_id`). The one-byte HS DCS read of register
`0xda` comes from the three existing P11 PB panel descriptions. This is a small
behavioral port; it does not import the Xiaomi display feature stack or expose
its proprietary userspace interfaces.

## Explicit selection

The behavior is disabled unless the selected panel has the boolean
`xiaomi,annibale-pb-quirks`. Parsing requires the exact PB ID
`0x0050313150420d0a`, a DCS backlight with room for DBV 15, a non-bridge panel,
and the published one-byte build-ID command/HS state. Invalid opt-in settings
fail panel creation rather than being silently ignored by the permissive
legacy backlight parser. A panel without the flag follows the existing path.

In the devicetrees repository, `ANNIBALE_DISPLAY_MODE=native` adds
`display/annibale-native-panel-test.dtbo` to the SUN non-VM build list. Empty
leaves it out; unknown values, non-SUN and trusted-VM selections fail. Compose
this overlay **after** `annibale-sde-display-mtp-overlay`. It sets only the flag
on the regular, P00 and P10 PB candidates. It neither selects a panel nor
changes command arrays, supplies, timing, backlight limits or audio family.
P11 PA and the NT37801 fallback are unaffected. Kbuild enumeration is not a
bootloader DTBO table or a complete Android installation change.

## Read, brightness and lifetime

On the first nonzero backlight request after initialization, the driver reads
the build ID while holding `panel_lock`. It uses the existing DSI receive path
with a unicast HS DCS read, acknowledgement request, one-byte receive buffer,
and command-master controller. The receiver now has a locked implementation
and an unchanged locking wrapper for existing callers, avoiding recursive
panel locking. Clock-on errors stop the transfer. Error interrupts, prepared
transfer resources and clocks are restored along the existing cleanup paths.

No read is attempted while uninitialized, in trusted VM, PLL bypass, ESD
recovery, a secure controller session or an unready host. Only an exact
one-byte successful response marks the revision valid. A failed/short read
leaves it unknown and logs the failure once per power cycle; normal backlight
writes continue without the revision-specific correction. There is no guessed
revision, boot-command-line override or repeated read on every slider update.
A skipped read may be attempted when a later request becomes eligible.

The correction occurs before inverted-DBV byte swapping. Zero remains zero;
revisions `0x80` and newer, unknown revisions, and values at or above 15 retain
their original values. Reset, disable and actual power-off invalidate the
cached revision/attempt state. Skipped power-off does not introduce the delay.
The 5 ms wait uses a sleep range in the existing sleepable power-off path.

This does **not** substitute `mi,max-brightness-normal` for the hardware range:
that property is not a direct maximum override in Xiaomi's production driver.
The original 16383 hardware maximum remains unchanged. HBM/LHBM, dimming,
flat mode, AOD, temperature compensation, panel ESD IRQ handling and the
Xiaomi display feature ABI still need their own integration and validation.

## Validation and limits

`python3 -B -m unittest discover -s sm8750-modules/tools/tests` compiles the
actual changed C function bodies with failure-injection mocks and UBSan.
Display tests cover all 256 revision bytes against all 65536 16-bit DBV values,
malformed opt-in configuration, transport failure/short-read/cache behavior,
skipped lifecycle/security states, byte ordering, write-error preservation,
and RX mutex/clock/IRQ/prepare cleanup. These are synchronous host tests, not
real DSI timing, kernel race or physical panel tests.

The full audio-profile external build and both interactive partition stages
must be regenerated when these driver sources change. The runtime subset
remains 186 TFA / 187 SIA modules; no additional driver is claimed by R19.
The paired DT validator composes 8 bases x 2 audio families x 2 display modes,
checks the native overlay changes only three boolean properties, and retains
all DTC warnings. The display negative checker exercises the actual Kbuild
file and rejects wrong IDs, read commands/states/lengths, ranges and PA gates.

HyperOS keeps its complete stock module/display stack. Do not enable this
native-only test overlay or replace only `msm_drm.ko` in that stack. Stock ABI
qualification is audited independently and still needs the unresolved
normal/recovery variants resolved. Neither path has a demonstrated boot or
working physical display from these host checks. This change is not a flash
package or a claim of complete HyperOS/native compatibility.
