# Task 4 report

Implemented resumable OTA Candidate handoff in `src/fota.c`.

- Added `fota_request_t`, `fota_status_t`, cancellation, and offset-aware chunk callback APIs.
- Added Resume/BCR checkpoint records with URL/ETag identity, expected length, offset, CRC/hash progress, and commit marker.
- Reconnects issue HTTP `Range: bytes=<offset>-`; duplicate chunks are verified against Candidate and out-of-order chunks fail safely.
- Candidate writes are serialized under `EXT_FLASH_OWNER_OTA`; timeout, size, identity, and write failures release the owner.
- Added dedicated EC800M OTA receive callback so OTA stream data is not routed to JT808.
- Added package/resume host replay tests.

Manifest verification now performs CRC32, payload SHA-256, product/hardware checks, and a fail-closed ECDSA hook. BCR serialization reuses `bootloader/include/bcr.h` and its exact packed layout/constants. HTTP headers are accumulated across modem reads; resumed transfers require a valid `206`/`Content-Range` response, while `200` safely restarts Candidate. Duplicate chunks are compared in full, in bounded blocks.

BCR `transaction_length` is the manifest payload length, excluding the manifest header.
`test_fota_package.py` includes a compiled runtime harness for the VERIFYING-to-BCR handoff; it captures the committed length and asserts it equals the payload length and not Candidate's manifest-plus-payload byte count. The source-level assertion remains as an additional guard.

The target application should provide a hardware-backed `fota_ecdsa_verify()` override. The default remains fail-closed.

Host tests pass. The repository environment did not provide `make`, so the embedded build could not be run here.

## F39 actions, queries and bounded replies

Implemented in `include/f39_reply.h`, `src/f39_reply.c` and
`tools/tests/test_f39_actions.py`.

- Added injected `f39_platform_t` callbacks for persistence, timer/network/JT808
  effects, GNSS receiver mode dispatch, relay safety and query
  identity data.
- Added bounded 192-byte replies with fail-closed overflow handling.
- `PARAM` and APN query replies never include APN usernames/passwords or other
  credential fields.
- Relay cut requires a valid fix and speed strictly below 20 km/h; restore is
  always permitted.
- RESET emits the success reply before invoking a bounded delayed-reset callback.
- GPSBDS changes validate the configured TAU804M/ATGM332D-F7N receiver before
  persistence and dispatch the selected mode after commit.

The action harness compiles and passes with GCC using
`-std=c99 -Wall -Wextra -Werror`. The Python launcher reports SKIP when the host compiler is not
discoverable through Python's PATH; direct GCC execution was used in this
environment.

## Fix round 1 review closure

- Replies now carry `reset_pending`/`reset_delay_ms`; `f39_execute` never
  schedules a reset before SMS handoff.
- Required effect callbacks are preflighted before persistence. Post-commit
  effects are delivered as non-failing callbacks, avoiding false rollback
  reports after a successful save.
- Relay query semantics match `relay_set(true)=cut`; non-finite and negative
  speed values fail closed.
- PID query derives the last 11 IMEI digits when no explicit PID is stored.
- PARAM includes bounded GNSS fields and `Success!`; all config/platform strings
  are length-bounded and non-NUL input fails closed.

Verification matrix (fresh GCC, `-std=c99 -Wall -Wextra -Werror`):

| Test | Normal launcher | `REQUIRE_GCC=1` / direct GCC |
|---|---|---|
| `test_f39_parser.py` | SKIP if compiler hidden from Python PATH | PASS |
| `test_f39_config.py` | SKIP if compiler hidden from Python PATH | PASS |
| `test_f39_dualset.py` | SKIP if compiler hidden from Python PATH | PASS |
| `test_f39_actions.py` | PASS (WinGet GCC auto-discovery) | PASS |
| `test_flash_config_migration.py` | SKIP if compiler hidden from Python PATH | PASS |
| feature guard | not run in Task 4 | deferred to Task 6 |
| `git diff --check` | PASS | PASS |
