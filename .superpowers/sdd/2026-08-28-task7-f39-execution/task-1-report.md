# Task 1 report: platform-neutral F39 command core

## Scope

Implemented the bounded F39 parser only.  It contains no MCU, storage,
network, timing, or side-effect code.

## RED evidence

Before production parser files existed, the new host harness was run with the
host GCC directory added to `PATH`:

```text
fatal error: f39_command.h: No such file or directory
fatal error: .../src/f39_command.c: No such file or directory
test_f39_parser: FAIL (C harness did not compile)
```

This was the expected missing-feature failure.

## GREEN verification

```text
python tools/tests/test_f39_parser.py
test_f39_parser: C harness PASS
test_f39_parser: PASS

REQUIRE_GCC=1 python tools/tests/test_f39_parser.py
test_f39_parser: C harness PASS
test_f39_parser: PASS
```

The harness compiles the real parser with C99, `-Wall -Wextra -Werror`.
`git diff --check` also passed; it emitted only pre-existing working-copy line
ending notices for user-owned dirty files.

## Files

- `include/f39_command.h`: typed F39 operations and bounded request/argument
  representation.
- `src/f39_command.c`: case-insensitive root parser, bounded copying, comma
  arguments, and bounded DUALSET star tokenization.
- `tools/tests/test_f39_parser.py`: real host C harness for accepted roots and
  malformed, oversized, removed, and delimiter edge cases.
- `Makefile`: adds the platform-neutral parser source to firmware sources.

## Commit

Recorded after the implementation commit is created.

## Concerns

- Task 1 deliberately validates grammar and bounds only.  Numeric ranges,
  settings/query semantics, DUALSET atomic prepare/commit, persistence, reply
  SMS, and hardware actions are owned by later tasks.
- The parser's argument spans reference its bounded copy in `f39_request_t`,
  so consumers must use `raw + offset` rather than retain ingress data.
