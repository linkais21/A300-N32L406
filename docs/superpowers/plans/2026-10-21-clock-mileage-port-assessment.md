# Clock, location coherence and mileage repair; migration assessment

User authorized the trajectory-related repairs and assessment of two migration
packages. Preserve existing user changes, source workbook, artifacts, firmware
identity and boot/Flash layout. No flashing, deployment, commit or push.
The export platform is unidentified; document its requirements rather than
modify an unrelated local server.

## Ordered implementation and acceptance

1. Save touched pre-task inputs/hashes in build-track-repair-20261021/before.
2. Add real-C failing regressions for GGA/RMC date and position coherence,
   midnight, stale dates, recovery and tick wrap. Implement bounded validation.
3. Capture original mileage on all new blind-zone paths, retain existing record
   envelope and byte-for-byte replay. Never backfill legacy records from live
   mileage. Test capture, append retry and replay after live mileage changes.
4. Calibrate RTC using vendor TIM9 internal LSI capture with bounded polling,
   no external pin remap or new ISR. Test arithmetic, overflow, timeout and
   cleanup; hardware operation remains HIL-only.
5. Schedule NTP using sleep-inclusive monotonic time, preserving retry limits,
   acquisition UTC and fix validity.
6. Assess G452 stationary fusion and D0/D1 packages against L406 interfaces,
   memory, storage, reset and log contracts. Do not transplant G452 binaries.
7. Build into an isolated directory with explicit targets preserving version
   metadata. Run targeted host regressions and release/resource gates. Reduce
   duplication only within affected modules if needed; never relax limits or
   remove unrelated functions. Review task diff and git diff --check.

## Evidence and delivery

Record command, return code, logs and input hashes in the isolated build
validation directory. Deliver repair details, migration feasibility/resource
constraints and required bench/HIL and export-platform validation. No hardware
success is inferred from compilation or host tests.
