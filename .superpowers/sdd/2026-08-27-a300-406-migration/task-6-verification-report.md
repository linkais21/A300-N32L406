# Task 6 Verification Report

## Scope

This verification task changes only `tools/tests/test_agnss_vendor_stream.py` and
this report. Production AGNSS parsers were not modified.

## TDD record

The pre-fix harness was run first. In the available Python environment it
reported `test_agnss_vendor_stream: SKIP (gcc unavailable)` and did not execute
the C assertions. The old harness also treated an incomplete Huada frame as a
send failure, so its later reset/retry assertions were unreachable when a C
compiler was available.

The harness was then rewritten with complete, checksum-valid test frames and
observable `gps_send_raw` call/byte counters.

## Covered contracts

- Huada F1D9 complete frame: UART send failure clears stream state and the same
  frame succeeds on retry.
- Huada `length=0xffff`: rejected immediately, followed by a successful valid
  frame proving stream reset.
- Huada fragmented frame: incomplete prefix waits and the completed frame is
  sent once.
- Zhongkewei malformed and incomplete responses: classified without GPS
  injection.
- Zhongkewei response fragmentation: prefix is buffered until complete.
- Zhongkewei GPS send failure clears buffered state and a complete retry
  succeeds.

## Verification output

With the compiler directory temporarily added to `PATH`:

```text
python tools/tests/test_agnss_vendor_stream.py
test_agnss_vendor_stream: C harness PASS
test_agnss_vendor_stream: PASS

REQUIRE_GCC=1 python tools/tests/test_agnss_vendor_stream.py
test_agnss_vendor_stream: C harness PASS
test_agnss_vendor_stream: PASS
```

Without `gcc` or `cc` in `PATH`, ordinary mode reports:

```text
test_agnss_vendor_stream: SKIP (gcc/cc unavailable)
test_agnss_vendor_stream: PASS
```

Strict mode remains a hard failure when neither compiler is available, as
required by the verification brief.

`git diff --check` passes for the verification changes.

## Remaining risk

The Zhongkewei binary response envelope exercised here is the fail-closed
envelope implemented by Task 6. Its exact on-wire format is still not
confirmed by a complete vendor protocol document or packet capture. Unknown
or malformed responses remain rejected and are never injected into GPS.
Target firmware compilation with `arm-none-eabi-gcc` remains a separate
environment prerequisite.
