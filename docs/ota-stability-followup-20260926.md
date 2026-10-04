# OTA stability follow-up (2026-09-26)

This note describes the current source tree. It is not a hardware release approval.

## BCR compatibility and install boundary

The 40-byte BCR format and Flash addresses are unchanged. New App builds set
`reserved = BCR_INSTALL_NOT_STARTED` (`0xB001`) when committing PENDING. The
Bootloader clears that marker in a durable BCR commit before erasing the first
internal App page. If a marked PENDING record is still at offset zero and no
verified LKG or factory image is available, the Bootloader can return to the
unchanged internal App after committing ACTIVE. It does not try this once the
marker has been cleared, since an interrupted first-page erase may already
have made the App unbootable. Legacy PENDING records with `reserved = 0` retain
the existing fail-closed install and rollback behavior.

Deploy the matching Bootloader before an App that emits the new marker. An older
Bootloader ignores the marker and cannot provide the pre-erase fallback.
Provision and verify a signed LKG or factory image before accepting OTA in the
field; vector validity alone is not a substitute for image authentication.

## Verification boundary

Host tests cover interrupted BCR writes, page erase/program/readback,
installation resume, rollback, trial reset counting, and the no-rollback
pre-erase case. App build and Flash guard report 104,636 / 106,496 bytes used,
1,860 bytes free. The low-headroom alert remains active. The HTTP OTA service
requires a token-bound progress report after a recorded download start before
marking a task SUCCESS. The v4.0 update check remains without `X-Device-Key`
during the agreed phased migration; enabling the Key requires a coordinated
device and server release.

Before release, perform HIL tests with real NOR and EC800M: cold power-up,
unavailable NOR with a valid App, erase/readback errors, power cuts before and
after the BCR marker commit and every internal page, damaged candidate and
rollback image, trial watchdog/software resets, weak-network Range resume,
and a successful signed upgrade through trial confirmation. Capture BCR,
checkpoint, UART, and server task states at each cut. Complete the RAM/stack
release gate and confirm the final Bootloader/App package identity. Host tests
and compilation cannot prove that a device will never brick or go offline.
