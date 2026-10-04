# AGNSS field diagnostics (N32L406)

The 2026-09-28 COM12 capture showed two A300_406 V3.077 online attempts ending in
`[AGNSS] result=0` after an AGPS-channel request was sent. Later GNSS fixes do
not establish that assistance was accepted. The saved capture also contains
output from a separate G452 V1.307 device; its `[AGNSS-METRIC]` line must not
be attributed to the N32L406 device.

The online transaction now emits one bounded summary at completion:

```text
[AGNSS] result=0 stage=2 reason=socket http=0 rx=0/0 tx=0 ack=0 seen=0 id=00
```

- `result=1` means every validated ephemeris frame received the expected ACK.
  It does not prove a shorter time to first fix.
- `stage`: 1 opening, 2 receiving, 3 validating, 4 cold start, 5 sending,
  6 waiting for ACK, 7 receive failure. Stage is captured before the state
  returns to idle.
- `reason`: `open`, `http-send`, `socket`, `deadline`, `http-header`,
  `header-limit`, `rx-overflow`, `body-overrun`, `late-data`, `frame`, `uart`,
  `ack-timeout`, `ack-nak`, `ack-other`, `stopped`, or `reset`.
- `http` is the parsed HTTP status, or 0 before a parseable status arrives.
  `rx` is received body bytes / declared Content-Length after a valid header;
  before a valid header it is the bytes collected so far / 0.
- `tx` counts ephemeris-frame UART send attempts, `ack` counts matching positive
  ACKs, `seen` counts candidate ACK frames handed to the validator, and `id`
  is the last ephemeris sub-ID in hex (`32` GPS, `33` BDS).

`[AGNSS-CACHE] tx_done=1 bytes=N` means every cached assistance frame received
the expected ACK. It does not prove a shorter time to first fix.
`tx_done=0 reason=1` means no valid matching cache; `reason=2` means the final
ACK or completion failed; `reason=3` means a cached read failed; `reason=4`
means frame injection failed, including NAK or ACK timeout.

For a hardware check, capture COM12 from before power-on through the first
valid fix. Keep the GNSS module awake and network service available while it
has no valid fix. Retain the full capture and actual flashed firmware identity.
If online `reason=ack-timeout`, capture the TAU804M UART4 TX/RX to determine
whether the module sent an ACK. The Huada A-GNSS application guide V1.4 requires
ACKs for ephemeris frames, while its binary protocol specification V2.3.6 says
non-CFG messages do not receive ACKs. Resolve this for the fitted module before
changing the ACK policy. Compare repeated cold-start time-to-first-fix trials
with AGPS enabled and disabled only after the injection path is verified.

The 2026-09-30 raw-response HIL App provides a COM12-only alternative when
probing both UART4 lines is impractical. On a first BDS frame NAK it prints
`[AGNSS-RAW]` timing, the complete `[AGNSS-TX]` frame and the 10-byte
`[AGNSS-RX]` response as hexadecimal text after the rejection. Save the full
COM12 file; the TX line is close to 1 KiB and screenshots can truncate it.
