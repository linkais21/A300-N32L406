# Task 2 report: PID/IMEI terminal identity and target version

## Outcome

- Added `terminal_id_derive()` and `terminal_identity_load()` as the single terminal-ID service.
- A valid 11-digit PID wins. With an empty PID, a bounded 7-to-15-digit decimal IMEI supplies its last seven digits. A non-empty invalid PID never falls through.
- JT808 registration, stored-auth startup, F39 PID re-registration, retry handling, and 0x0107 all use the same validated identity. Invalid identity remains offline and logs `[808] identity invalid` at most once per five seconds.
- 0x0107 success uses protocol length fields and the complete 35-byte target version; invalid identity returns bounded terminal general response result `1` for `0x8107`.
- `FW_FULL_VERSION`/`FW_VERSION_STR` resolve exactly to `T360-A300_406_20260823000000,V3.000`; `FW_BUILD_DATE` remains independently generated.

## TDD evidence

RED command:

```powershell
$env:REQUIRE_GCC='1'; python tools/tests/test_terminal_identity.py
```

Initial result: exit 1. GCC reported missing `terminal_identity.h` and `src/terminal_identity.c`, followed by `test_terminal_identity: FAIL (C harness did not compile)`.

Release-guard RED: after adding behavioral assertions, the test exited 1 with `AttributeError: module 'release_guard' has no attribute 'fixed_identity_findings'`.

Integration RED: the real JT808 host harness observed two IMEI reads for one initial registration, proving the double-derivation race. Later focused RED runs also exposed the existing 0x0107 `strncpy` truncation warning under `-Werror` and missing stateful F39 re-registration.

Final GREEN:

```text
test_terminal_identity: C99 -Wall -Wextra -Werror PASS
test_terminal_identity: PASS
test_f39_config: C99 -Wall -Wextra -Werror PASS
test_f39_config: PASS
test_f39_actions: PASS
test_f39_end_to_end: both host executables PASS
test_feature_guards: PASS
release-guard: PASS
git diff --check: exit 0
```

The identity harness executes real `terminal_identity.c`, `jt808.c`, and `jt808_params.c`. It covers PID precedence, IMEI lengths 7/8/14/15, malformed/short/overlong input, NUL termination, registration, stored auth, invalid diagnostic rate limiting, F39-requested re-registration, initial and timeout send failures, exact five-second retry timing, and 0x0107 success/failure frames.

## Mutation evidence

Each actual consumer was temporarily mutated, `python tools/release_guard.py` was run, and the source was immediately restored:

- `src/main.c`: `strcpy(..., "1234567")` -> FAIL, `<fixed-terminal-id>: 1234567`.
- `src/jt808.c`: static literal `"7654321"` -> FAIL, `<fixed-terminal-id>: 7654321`.
- `src/jt808_params.c`: multiline `memcpy(..., "9012345", 7)` -> FAIL, `<fixed-terminal-id>: 9012345`.

The permanent guard regression test additionally copies all four real consumers, including `src/terminal_identity.c`, into a temporary release tree and mutates each through the complete `scan()` path. Wrong generator, `FW_VERSION_STR`, and `FW_FULL_VERSION` values are also rejected.

## Full host matrix

The required pre-commit baseline matrix was run once with `REQUIRE_GCC=1`, excluding the new focused identity script from the pre-existing 25-script count:

```text
MATRIX TOTAL=25 PASS=25 FAIL=0 SKIP=0
```

All 25 individual scripts reported PASS.

## Release and protected-change guards

- `python tools/release_guard.py`: `release-guard: PASS`.
- `git diff --check`: exit 0.
- `git diff --cached --check`: exit 0.
- `task-6-rereview-1.md` was not touched or staged.

Protected comparison method:

1. Reconstructed expected pre-task files by archiving HEAD and applying `task-2-protected-before.patch`.
2. Copied current protected files and reverse-applied the cached Task 2 `src/jt808.c` patch.
3. Compared normalized Git blobs for `include/i2c_accel.h`, `src/flash_config.c`, `src/hw_init.c`, `src/i2c_accel.c`, and `src/jt808.c`; all matched.
4. For overlapping `include/build_version.h`, all lines except the authorized `FW_FULL_VERSION` line matched the reconstructed user file, and the authorized line matched the exact target version.

Result: `PROTECTED_AUDIT_PASS=True`.

Exact cached implementation file list before adding this report:

```text
Makefile
gen_version.ps1
include/build_version.h
include/jt808.h
include/terminal_identity.h
src/at_config.c
src/jt808.c
src/jt808_params.c
src/main.c
src/terminal_identity.c
tools/release_guard.py
tools/tests/test_f39_end_to_end.py
tools/tests/test_terminal_identity.py
```

## Independent review and self-review

Independent specification review: PASS after real JT808/F39 consumer coverage, full-scan mutations, and double-derivation removal.

Independent quality review: PASS after correcting variable-length 0x0107 fields, complete version reporting, stateful re-registration, initial/timeout send-failure retry behavior, and guard bypasses.

Self-review confirmed static bounded buffers only, no allocation, exact PID precedence, no invented fallback, one protocol-valid 0x0107 failure response, retained forced registration across send failures, and no staged user-owned hunks.

Commit message: `fix: derive JT808 identity from PID or IMEI`.

## Fix Round 1

Resolved all four Important findings from `task-2-review.md`:

- F39 `PID` and `PARAM` now adapt the bounded platform IMEI and delegate to
  `terminal_id_derive()`. Both emit exactly seven digits; a non-empty malformed
  PID fails without falling through to IMEI. The IMEI rule remains numeric
  length `>=7` within the 15-byte API bound, using the last seven digits.
- Each successful 0x0100 send records its registration generation and message
  serial. A 0x8100 is accepted only while registering and only when its body
  references that active generation/serial. F39 re-registration and connection
  loss invalidate the previous response token.
- Idle and registration-retry identity failures share one five-second bounded
  `[808] identity invalid` diagnostic helper.
- The release guard includes `src/f39_reply.c`, requires each identity consumer
  to call its permitted central service, and rejects numeric fixed IDs expressed
  as ordinary/split literals or character/hex byte initializers through the full
  `scan()` path.

TDD RED evidence before production changes:

```text
$env:REQUIRE_GCC='1'; python tools/tests/test_terminal_identity.py
AssertionError: release_guard.fixed_identity_findings(split)
exit 1
```

After enabling GCC for the integration command, the F39 E2E test also exposed
the expected new link dependency before its harness was updated:

```text
undefined reference to `terminal_id_derive'
subprocess.CalledProcessError
exit 1
```

Fresh final verification, with WinLibs GCC added to `PATH` and
`REQUIRE_GCC=1`:

```text
test_terminal_identity: C99 -Wall -Wextra -Werror PASS
test_terminal_identity: PASS
test_f39_actions: PASS
test_f39_end_to_end: PASS / PASS
release-guard: PASS
test_feature_guards: PASS
git diff --check: exit 0
TASK2_ROUND1_VERIFICATION_PASS
```

New harness coverage includes PID precedence and empty-PID IMEI fallback for
both F39 replies, malformed non-empty PID rejection, a PID change between an old
registration send and response, successful processing of the current response,
disconnect-stale response rejection, and bounded retry-time invalid-identity
diagnostics. The review-follow-up also injects the last valid response after a
retry detects invalid identity and verifies that response is rejected.

Independent review follow-ups retained the forced re-registration intent until
a matching active 0x8100 is accepted. The disconnect harness now proves that a
reconnect sends a fresh 0x0100 with the new seven-digit identity rather than
authenticating with the previous PID's stored code. Guard follow-ups use
brace-balanced named-function extraction, so an adjacent dead service call
cannot satisfy the permitted-call requirement.

Fix-round independent review result: PASS, with no remaining Critical,
Important, or Minor findings. The post-review verification marker was
`TASK2_ROUND1_FINAL2_VERIFICATION_PASS`.
