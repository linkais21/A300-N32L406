# Blind-Zone Scratch Recovery Design

## 1. Approved layout

The external-Flash blind-zone partition remains unchanged at `0x110000` with a total size of 644 KiB. Its internal layout becomes:

- Metadata journal: `0x110000`, 4 KiB.
- Normal record area: `0x111000`, 636 KiB, 159 sectors, 10,176 physical 64-byte slots.
- Repair scratch sector: `0x1B0000`, 4 KiB.
- Logical FIFO capacity: 9,900 records, leaving 276 physical spare slots.

The scratch sector is never part of the logical FIFO and cannot store ordinary location records.

## 2. Sector repair transaction

A complete record body with valid magic, format, length, event ID, sequence and CRC but without the final commit marker is a `PREPARED` record. Recovery finalizes or adopts it before accepting another event. A partially written body that fails structural validation or CRC is a damaged slot.

Damaged slots may not accumulate. Before the store becomes READY or accepts another append, it repairs each affected data sector:

1. Erase the scratch sector.
2. Copy every valid record from the victim sector into scratch slots 1 through N, preserving complete record bytes and physical-slot order. Because the victim contains at least one damaged slot, at most 63 valid records exist and fit beside a 64-byte scratch header.
3. Write and verify a 64-byte scratch header containing magic/version, victim sector index, 64-bit original-slot bitmap, record count, generation, payload CRC and a commit marker written last.
4. Only after the scratch header is committed, erase the victim sector.
5. Restore copied records to their exact original physical slots and verify them.
6. Erase scratch, completing the transaction.

On boot, a valid committed scratch header always takes priority over ordinary recovery. Recovery erases the victim again, restores all saved records, verifies them, then erases scratch. A cut before the scratch header commit leaves the victim untouched. A cut at any later phase is safely repeatable from the committed scratch image.

The scratch header and 63 record images exactly fill one 4 KiB sector. The slot bitmap maps each image, in ascending original-slot order, back to its original slot without per-record mapping overhead.

## 3. Append durability and identity

Each caller event has a nonzero monotonically generated 32-bit `event_id`, stored in the record body and protected by CRC. An append retry is the same transaction only when its event ID matches; equal payload bytes do not identify an event.

The append contract is:

- `OK`: the event is durably committed and logically adopted.
- `PENDING`: a prepared/uncertain event is durably recognizable and bounded recovery is in progress; poll with the same event ID and payload.
- `BUSY`: ownership or maintenance prevents admission; the event was not admitted.
- `IO_ERROR`: the event was definitely not durably prepared; the caller may retry the same event.
- `STALE`/`INVALID`: the supplied transaction identity is obsolete or malformed.

Once the body and CRC are verified, losing the final marker cannot lose the event across reset: boot recognizes PREPARED, finalizes it in the same physical slot, and reconciles metadata. A torn invalid body triggers sector repair, reclaiming that same slot before retry. This prevents the full-span poisoned-slot state.

## 4. Bounded caller queue and alarms

JT808 owns a fixed two-entry event queue. Each entry stores event ID, encoded location body, captured alarm mask and per-bit alarm generation snapshot. One entry may be pending in blind-zone storage while one later event waits. Queue overflow increments a saturating diagnostic and returns not-admitted to the event producer.

Alarm bits have per-bit monotonically increasing generations. Completing event A clears a captured bit only when that bit's current generation still equals A's snapshot. Re-raising the same bit, or raising another alarm while A is pending, remains queued for event B.

Angle-triggered reporting advances its accepted-heading baseline only when the JT808 event is sent or admitted to the bounded queue. BUSY/overflow does not consume the trigger.

## 5. Existing guarantees retained

- Blind-zone code uses only `ext_flash_store` under `EXT_FLASH_OWNER_BLIND_ZONE`; OTA priority and immediate blind-zone acquisition remain.
- Metadata consumption stays tombstone-first; an ACKed replay batch is cleared only after local consume returns `OK`.
- Raw recovery ignores tombstoned records, handles physical wrap and holes, and is incremental.
- Replay remains one batch in flight, uses JT808 `0x0704`, and consumes only an exact successful `0x8001` bound to serial, authenticated channel and session generation.
- Static allocation only; each main-loop call has bounded reads/writes.
- Persistent format v1 and the earlier local v2 development format were never released. Unknown/old media fails closed with a diagnostic; no field migration is required.

## 6. Required verification

The NOR harness must enforce one-way programming, 4 KiB erase and injected failure at every byte/phase. It must cover scratch backup header cuts, victim erase cuts, every restore record cut, scratch erase cuts, PREPARED reset outcomes, exact `count=9900` capacity, physical wrap, distributed damaged slots, and repeated repair cycles.

The terminal counterexample is mandatory: begin with 9,900 live records and the maximum allowed damaged-slot pressure, use the last erased slot for PREPARED, reset/finalize it, then prove the next event repairs/reuses space and completes without permanent `IO_ERROR`.

Caller tests cover two identical payloads with distinct IDs, pending A plus B, same-bit and different-bit alarm re-raise, queue overflow saturation, angle-trigger retry, reboot during PREPARED, and no duplicate local append after recovery.

Completion requires focused tests, the full host matrix with `REQUIRE_GCC=1`, release guard, protected-user-hunk audit, independent review per task, and finally an ARM/map gate in Task10. Host tests do not substitute for the target build or hardware power-cut matrix.
