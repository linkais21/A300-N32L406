# A300_406 Version, BeiDou Status, and Terminal Attributes Design

## Scope

This change establishes one release identity contract for the N32L406 firmware and the FOTA management platform, corrects the JT/T 808 location status for BeiDou positioning, and adds one proactive `0x0107` terminal-attributes upload per authenticated channel after every device boot.

No branch, commit, deployment, or device flashing is part of the implementation. Generated firmware must remain under `A300-first/build/`.

## Release Identity Contract

The firmware version for this release is exactly `T360-A300_406_20260823000000,V3.001`. Future behavior-changing releases increment only the three-digit revision (`V3.002`, `V3.003`, and so on); the `T360-A300_406_20260823000000,V3.` prefix remains fixed unless the user explicitly changes the product baseline.

The following identities are distinct and must not be substituted for one another:

- OTA management device model: `A300-406`
- JT/T 808 terminal model: `T360-A300`
- JT/T 808 manufacturer ID: `70110`
- Firmware version: `T360-A300_406_20260823000000,V3.001`

A machine-readable release contract will be the source used by version generation and release validation. Compiled C constants and FOTA platform defaults remain explicit but are checked against that contract. The FOTA platform will normalize the current A300 aliases to `A300-406` so firmware uploads, managed devices, and update tasks use one model key.

## `0x0200` Location Status

For a current valid GNSS fix, the status word sets both bit1 (valid positioning) and bit19 (positioning used BeiDou satellites). A retained position reported while GNSS is unavailable clears bit1, so it is not represented as a current fix, but preserves bit19 to identify the trusted position source as BeiDou. Longitude, latitude, ACC, and other existing status bits are unchanged.

The rule applies to every firmware path that constructs a `0x0200` body, including immediate wake reports and stationary-sleep retained-position reports. Historical data must never set the current-position-valid bit.

## `0x0107` Terminal Attributes

One shared body encoder serves both proactive uploads and replies to platform `0x8107` queries. The encoded body uses the JT/T 808-2013 layout:

- terminal type `0x000D`: passenger, ordinary freight, and taxi applicability;
- manufacturer ID `70110` (five bytes);
- terminal model `T360-A300`, zero-padded to 20 bytes;
- seven-byte terminal ID derived by the existing canonical identity service;
- live SIM ICCID encoded into ten BCD bytes;
- zero-length hardware version, because no confirmed hardware-version string exists;
- full firmware version `T360-A300_406_20260823000000,V3.001`;
- GNSS capability `0x02` (BeiDou support);
- communications capability `0x20` (TD-LTE support).

The EC800M identity layer accepts 19 or 20 hexadecimal ICCID characters (`0-9A-Fa-f`). The terminal-attributes encoder preserves those nibbles in the ten-byte field, with a leading zero nibble for 19-character values. Invalid length or characters outside that range must not produce fabricated all-zero attributes. Query handling returns a failure response; proactive upload remains pending for a bounded retry sequence and logs the reason.

## Per-Channel Boot Behavior

CH0 and configured CH3 maintain independent `pending`, `sent`, retry-count, and retry-deadline state. Each channel becomes pending when its first authentication succeeds after boot. A successful or transport-ambiguous send marks that channel complete because retransmission could duplicate a packet already accepted by the modem. A definite send failure retries with bounded backoff. Link reconnection or re-registration during the same boot does not resend after completion. `jt808_init()` resets both channels for the next real device boot.

A platform `0x8107` query always receives a fresh `0x0107` response on the requesting channel, even if the proactive boot upload already completed.

## Verification

Host tests must demonstrate RED then GREEN for release identity validation, exact `0x0200` bits, complete `0x0107` field bytes, invalid identity/ICCID rejection, CH0/CH3 once-per-boot behavior, bounded retry, and query response routing. Final validation includes targeted regressions, all related host tests, ARM build, `release-guard`, `ram-guard`, `git diff --check`, final binary hashes, and size reporting.

Real-device/HIL validation remains required for actual ICCID acquisition, dual-platform authentication timing, modem send ambiguity, BeiDou fix status, and reboot-only upload behavior.
