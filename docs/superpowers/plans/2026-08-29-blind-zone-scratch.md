# Blind-Zone Scratch Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the blocked blind-zone allocation/recovery path with a scratch-backed, power-loss-safe 9,900-record FIFO and lossless bounded JT808 event admission.

**Architecture:** A dedicated 4 KiB scratch sector transactionally backs up and restores any data sector containing a damaged slot, preventing physical holes from accumulating. Records carry durable event IDs and PREPARED recovery semantics; JT808 uses a two-entry static event queue with generation-safe alarm completion.

**Tech Stack:** C99 firmware, N32L406CBL7, BY25Q16ES NOR Flash, `ext_flash_store`, JT808-2013, Python-launched strict host C harnesses.

## Global Constraints

- Blind-zone partition remains `0x110000` / 644 KiB: 4 KiB metadata, 636 KiB normal data, 4 KiB scratch at `0x1B0000`.
- Physical slots are exactly 10,176; logical capacity is exactly 9,900.
- Never copy N32G452 platform files or call raw SPI from blind-zone production code.
- Scratch is repair-only and must never contain an ordinary logical FIFO record.
- Static allocation and bounded operations only; OTA ownership has priority.
- Preserve all six user-owned dirty files; stage only exact task hunks in overlapping `src/jt808.c`.
- Version remains exactly `T360-A300_406_20260823000000,V3.000`.
- Each task requires RED/GREEN, one scoped commit and independent review before the next task.

---

### Task 1: Implement scratch-backed sector repair and PREPARED records

**Files:**
- Modify: `include/blind_zone.h`
- Modify: `src/blind_zone.c`
- Modify: `tools/tests/test_blind_zone_store.py`
- Modify: `tools/tests/test_ext_flash_layout.py`

**Interfaces:**
- `blind_zone_record_t` gains nonzero `uint32_t event_id`.
- `blind_zone_append()` matches retries by event ID and payload.
- Scratch recovery is internal and completes before `blind_zone_ready()` becomes true.

- [ ] Add RED layout assertions for metadata 4 KiB, data 636 KiB, scratch 4 KiB at `0x1B0000`, 10,176 physical slots and 9,900 logical capacity.
- [ ] Add RED NOR tests for PREPARED reset/finalize, invalid torn-body repair, scratch backup/header/victim-erase/restore/scratch-erase cuts, and exact original-slot restoration.
- [ ] Add the RED terminal counterexample with full logical capacity, distributed damage pressure and repeated post-PREPARED append; require forward progress without permanent I/O failure.
- [ ] Implement the 64-byte committed scratch header, 64-bit slot bitmap, ordered record images, boot-priority restoration and immediate damaged-sector maintenance.
- [ ] Make record body/CRC/event ID independently validate PREPARED; finalize/adopt it in place after reboot. Match polling transactions by event ID, never payload alone.
- [ ] Verify repair never starts victim erase before committed scratch, and no API becomes READY while scratch/damage maintenance is incomplete.
- [ ] Run store/layout/ext-Flash/FOTA focused tests and `git diff --check`.
- [ ] Commit only Task 1 files as `fix: add scratch-backed blind-zone recovery`, then request independent storage review.

### Task 2: Add bounded JT808 event queue and generation-safe alarm completion

**Files:**
- Modify: `src/jt808.c`
- Modify if required: `include/jt808.h`
- Modify: `src/mileage.c`
- Modify: `tools/tests/test_blind_zone_replay.py`
- Create: `tools/tests/test_jt808_event_queue.py`
- Modify: `tools/tests/test_terminal_identity.py`
- Modify: `tools/release_guard.py`

**Interfaces:**
- Produces a two-entry static event FIFO containing event ID, encoded body, alarm mask and per-bit generation snapshot.
- `jt808_send_location()` returns admitted/sent success only when the event is sent or queued; not-admitted remains retryable by producers.

- [ ] Add RED tests for identical payload/distinct event IDs, pending A plus queued B, same/different alarm re-raise, bounded overflow counter, and ordered service after recovery.
- [ ] Add RED mileage test proving heading baseline does not advance on not-admitted and advances exactly once on admission.
- [ ] Implement nonzero monotonic event IDs, two-entry FIFO, saturating overflow diagnostic and same-event polling of the FIFO head.
- [ ] Implement per-alarm-bit generations and clear only the captured generation after confirmed send/adoption; preserve alarms raised while A is pending.
- [ ] Route periodic, alarm and angle events through the queue; query responses remain send-only and never enter blind-zone storage.
- [ ] Preserve exact authenticated channel/session replay and ACK rules from the reviewed Task 3 state.
- [ ] Run event-queue/replay/identity/F39 focused tests and `git diff --check`.
- [ ] Stage `src/jt808.c` by exact Task 2 hunks against the protected snapshot. Commit as `fix: queue pending JT808 location events`, then request independent caller/session review.

### Task 3: Close scratch redesign verification

**Files:**
- Modify: `docs/task10-release-gates.md` if it exists, otherwise create `docs/task3b-blind-zone-verification.md`
- Modify only when a failing regression requires it: Task 1/2 source or test files

**Interfaces:**
- Produces exact host evidence and remaining Task10 target/hardware gates.

- [ ] Run every scratch transition fault injection, PREPARED reset case, full-capacity/repeated-repair test, event queue/alarm/angle test, replay ACK test and ext-Flash ownership test.
- [ ] Run every `tools/tests/test_*.py` with `REQUIRE_GCC=1`; require zero FAIL and zero SKIP.
- [ ] Run `tools/release_guard.py`, `git diff --check`, and the six-file protected-diff comparison.
- [ ] Document logical/physical capacity, scratch transaction phases, test counts, exact commits and the explicit absence or result of ARM/map/hardware evidence.
- [ ] Commit verification only as `test: verify scratch-backed blind-zone recovery` and request final cross-task review before Task10.
