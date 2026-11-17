# Annibale development direction

The user selected this direction on 2026-11-16: continue adapting kernel 6.6,
and attempt a newer kernel only after normal daily operation is established.

The active baseline is the existing 6.6.144 source/kernel build. Do not replace
it with a 6.12 experiment merely because another Qualcomm platform has a
newer-kernel port. Read-only comparison with other ports can inform fixes.

Current priorities are the display/touch path, complete source module and boot
assembly, and the outstanding camera and charging integration. Keep native
source modules and HyperOS stock modules as separate ownership profiles;
qualification of one does not qualify the other.

Before switching focus to a newer kernel, establish real-device boot and the
expected daily functions: display/touch, storage, connectivity, audio, cameras,
charging, repeated screen-off/wake and acceptable standby behavior. Retain
logs and a reproducible working baseline. Successful compilation, static ABI
checks and DT composition alone do not meet that milestone.

R20 continues on 6.6. No newer-kernel development branch is created by this
round. Detailed per-round evidence and unresolved limitations are recorded in
`annibale-r19-validation.json`, `annibale-r20-validation.json`,
`annibale-display.md` and `annibale-touch-power.md`.

R21 moves toward a first recoverable boot test: retained-stock normal-boot
provider selection, an unsigned offline kernel-only candidate, and read-only
live-device evidence. See `annibale-boot-readiness.md`. This does not supersede
the native source-module path or qualify a flash without the remaining gates.

R22 uses the restored OS4.0.6.0 live baseline and expands native source selection
to camera, video, EVA and Bluetooth SLIM transport. Annibale-specific v1/v2
multimedia overlays preserve board selectors. This is integration of already
built drivers, not four new driver ports. See `annibale-multimedia.md` and
`annibale-r22-validation.json` for current reproducible evidence and limits.
