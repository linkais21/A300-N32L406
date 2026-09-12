# Binary-safe QIRD FOTA Design

## Problem

The EC800M generic AT waiter scans the complete `AT+QIRD` response for a line
equal to `OK`. OTA payload bytes are binary and may themselves contain
`\r\nOK\r\n`. V3.018 contains that sequence at offsets 90968, 90977, and
91080, causing the waiter to return before the declared QIRD payload and real
terminal result have arrived. The consumed but rejected bytes then corrupt the
resumed image, so final SHA-256 verification fails.

## Design

Add a dedicated, bounded QIRD collector in `src/ec800m.c`. It first parses the
`+QIRD: <length>\r\n` header, then treats exactly that many bytes as opaque
binary data. Only bytes after the declared payload may satisfy the terminal
`OK` or `ERROR` result. The collector retains the existing 400-byte chunk,
three-second timeout, AT ownership, watchdog service, and eight-read cooperative
budget.

Keep the existing continuation mask so a full chunk schedules another bounded
main-loop drain. Do not change HTTP, Range, Flash checkpoint, package, signing,
or platform contracts.

Add stage-specific FOTA verification diagnostics without printing firmware
content, hashes, signatures, tokens, or device keys. A failed verification
must identify header, package read, SHA-256, signature, CRC, vector, BCR, or
authorization stage.

## Verification

The host modem test must reproduce a QIRD payload containing an embedded
`\r\nOK\r\n` split from the real terminal `OK`; it must fail before the change
and deliver every payload byte afterward. Existing malformed framing, URC
demultiplexing, OTA flow, package, diagnostics, release, RAM, and stack tests
must remain green. Final OTA behavior requires real-device verification.

## Release Pair

- V3.019: SWD baseline containing the binary-safe downloader.
- V3.020: OTA target built from the same functionality with only the version
  identity incremented.

## Field Follow-up: Tail URC Interleaving

V3.019 proved that the binary payload boundary is now respected, but also
captured a complete 400-byte QIRD payload followed by an asynchronous URC
before the terminal `OK`. Buffering the header, payload, URC, and terminal
result together exhausted the 512-byte AT response buffer and discarded the
otherwise complete payload.

The follow-up implementation must not increase `AT_RESP_MAX` to the G452 value
of 2048 because the N32L406 SRAM budget is only 24 KiB. Instead, QIRD is parsed
as three streaming phases:

1. Reuse the existing line accumulator until a valid `+QIRD: <length>` line is
   received; dispatch preceding complete URCs normally.
2. Store exactly the declared binary payload in the existing 512-byte response
   buffer without line scanning.
3. Return to the line accumulator, defer any intervening URCs, and finish only
   on a complete terminal `OK` or fail on `ERROR`.

This keeps static RAM unchanged and supports payload-contained result-looking
bytes, fragmented input, and URCs between payload and the modem result.

The new release pair is V3.021 for SWD and V3.022 for OTA.
