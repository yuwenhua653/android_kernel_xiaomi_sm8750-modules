# R20: touch temperature and charger-state lifetime

R20 continues the 6.6 native source qualification path. It fixes the existing
Warsaw-family Goodix candidate; it does not establish that this is the exact
P11 touch/THP driver, add a new touch controller, or complete display/gesture
support. The published source provenance remains MiCode
`vendor_xiaomi_proprietary_touch-driver`, commit
`57d9a0225b031f4b444251117f3ecc9deae71128`, `warsaw/`. Original headers and
licensing are retained. The public Xiaomi core declares `MODULE_LICENSE("GPL")`.

## Temperature access and shutdown

`get_bms_temp_common()` now balances its power-supply reference on both success
and property failure. Battery-first lookup and BMS fallback-on-absence are
unchanged. Invalid values are checked by signed range comparisons rather than
`abs()`, so `INT_MIN` cannot overflow that check. Negative temperatures now
round to the nearest degree with ties away from zero, consistently in periodic
updates and the forced Goodix resume update. The accepted raw interval remains
strictly between -1000 and 1000 tenths of a degree.

The temperature task pointer is now per panel instead of one global pointer.
The worker receives the actual panel object, maintains its own last-successful
temperature, and sends its notification to that panel's ID. It advances the
cache only when the firmware command succeeds, allowing a failed command to
be retried at the next polling interval.

Both waits include the stop condition. The former unconditional 5/10-second
sleep becomes an interruptible timed wait, which also wakes on pause. Positive
charging state uses five seconds; disconnected/unknown state uses ten seconds.
There is no new polling-rate or measured power-saving claim.

A callback mutex serializes periodic temperature sampling/firmware notification
with pause. When pause returns, a periodic temperature callback that was
already running has completed. A separate lifecycle mutex serializes task
creation and stop; `kthread_stop()` never holds the callback mutex. Task creation
failure leaves the optional poller disabled with a diagnostic, never an
`ERR_PTR` stored for later stopping. The wait queue is initialized before task
creation or callbacks become visible.

Goodix remove and shutdown stop the poller after unregistering display PM
notifications and before controller power teardown. Xiaomi panel unregister
also performs an idempotent stop **before** freeing notification buffers or
clearing the callback table. Invalid touch IDs are rejected before shifting
the registration mask. A stopped task cannot be reactivated by a late normal
resume request; a later registration can create a fresh task.

This only drains the periodic temperature task. Existing mmap users, all other
vendor callbacks, IRQ/firmware-update teardown and full hot-unplug lifetime
are not thereby proven safe. R20 does not claim a complete removal audit.

## Charger-state replay

Goodix now explicitly restores both connected and disconnected states after
resume. The old restore helper sent only the connected command and used a
global controller pointer instead of its argument. A power-supply update now
serializes its cached state and firmware write with the existing controller
PM mutex: while suspended, it updates the cache for later replay; while awake,
it sends the corresponding state. An initial negative/unknown status does not
turn charger mode on. Firmware failures are logged and do not leave the mutex
held. No new command format or charging-controller policy is introduced.

The Xiaomi outer resume worker already also replays charging status. This fix
makes the Goodix resume path correct independently, including other callers;
it is not evidence of an observed K90 unplug or touch-sensitivity failure.

## Validation and boundaries

The host fixture compiles actual source function bodies with UBSan and pthread
mocks. It checks battery/BMS selection and balanced references, signed range
and rounding, two independent panel tasks, a failed firmware command followed
by a successful retry, invalid sensor data, task-creation failure, pause while
a firmware callback is blocked, stop from both idle and timed waits, and
sixteen additional registration-like start/pause/stop cycles. Charger tests
exercise connected/disconnected/unknown states, suspend cache and resume
replay, missing callback and firmware failure. Host threads test useful
interleavings but do not replace kernel lockdep, race testing or physical PM.

The full 91-module build and TFA/SIA interactive stages are regenerated because
the shared touch header and module interfaces changed. Their runtime subsets
remain 186 and 187 modules. The kernel Image and DT sources are unchanged;
R19's DT results are retained as prior evidence, not claimed as new R20 runs.
HyperOS retains its coherent stock module family. Real P11 firmware/THP,
gestures, suspend/resume, daily usability and both ROM boot paths remain
unverified.
