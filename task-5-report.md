# Task 5 report

Added bounded dual-slot AGNSS metadata/storage with commit-marker validation,
newest-valid selection, CRC32/SHA-256 readback verification, and a scheduler
that defers during OTA, retries after 60 seconds, performs one boot read, and
refreshes only while GNSS is invalid. Unknown receiver types are a no-op.
# Task 5 report

Integrated the production SMS path with F39 parsing/execution and bounded replies.

- Preserved sender identity through the two-entry FIFO and routed `+CMT` messages to `f39_execute`.
- Added injected platform binding plus A300_406 defaults for config persistence, timer/network/JT808/GNSS/relay effects and live query fields.
- Replies are sent to the original sender; send busy/failure returns without scheduling RESET. RESET is scheduled only after successful SMS handoff.
- DUALSET effects remain deterministic (`timer -> network -> GNSS -> JT808 -> remaining`) and removed commands never invoke platform callbacks.
- Added `tools/tests/test_f39_end_to_end.py` covering two senders, config save/action replies, busy/failure, reset handoff, removed commands and effect order.

Verification (`REQUIRE_GCC=1`): end-to-end, SMS ingress/whitelist/boundary, parser, config, DUALSET and actions all PASS; `git diff --check` PASS.

## Fix round 1

- Replaced the unconditional `sms_send` stub with an EC800M bounded non-blocking `CMGS` state machine (busy, prompt timeout, result timeout, `+CMGS` success and `ERROR` failure).
- Changed modem `CNMI` to `2,2` so direct `+CMT` URCs feed the existing ingress FIFO.
- RESET handoff now waits for actual modem send completion before scheduling reset.
- Default `PARAM` binding refreshes ACC from the PA3 input; e2e covers default transport, busy/failure and reset handoff.

## Re-review fix round 1

- CMGS TX now uses a serialized, READY-gated state machine with bounded TXDE/TXC waits and watchdog reloads.
- Reset cancels in-flight SMS state and reports failed handoff; prompt and result parsing are scoped to CMGS context (`>` at line start, `+CMGS:`/`+CMS ERROR:` only).
- Non-RESET handoff failures emit bounded diagnostics; production default remains non-blocking.

## Re-review fix round 2

- CMGS result handling accepts exact `ERROR`, `+CMS ERROR:` and `+CMGS:` lines.
- Power-off, reset and init cancel pending SMS state, release AT ownership and signal failure.
- Periodic CSQ uses the shared AT owner instead of raw UART writes.
- Default replies retain bounded sender/text state and retry asynchronous failures twice with fixed backoff; terminal failure is diagnosed, and RESET schedules only after confirmed send completion.

## Re-review fix round 3

- CMGS prompt and result phases now fail immediately on exact `ERROR`/`+CMS ERROR:` lines.
- Retry exhaustion clears retained sender/reply and reset handoff state, preventing stale RESET scheduling.

## Re-review fix round 4/5

- Added a real production-chain host harness linking `ec800m.c`, `peripherals.c`,
  `at_config.c`, and F39 modules.  It drives the DMA UART5 ring through
  `ec800m_process()`, verifies sender-preserving `+CMT` ingress, CMGS prompt,
  `+CMGS` success, plain `ERROR` failure, retry exhaustion and RESET handoff,
  and injects a TCP-payload/SMS owner race.
- Extended AT ownership across the complete TCP `QISEND` prompt, payload and
  `SEND OK` transaction using a dedicated TCP owner.  SMS admission now fails
  boundedly while any AT owner is active.
- Consolidated EC800M UART TX paths behind a length-aware 100 ms stall margin
  (plus wire-time budget) with watchdog reloads, including modem-alive probe
  and SMS/TCP payloads.

Verification (`REQUIRE_GCC=1`): `python tools/tests/test_f39_end_to_end.py`
PASS (unit and real production-chain harness).  The brief-mandated SMS/F39
ingress, whitelist, execution boundary, parser, config, DUALSET and action
checks also pass under `REQUIRE_GCC=1`; `git diff --check` is clean.  The broad
`tools/tests` run is 33 passed / 1 unrelated pre-existing host-shim compile
failure in `test_ext_flash_store_host.py` (missing shim headers/macros).
