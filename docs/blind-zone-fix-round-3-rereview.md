# Blind-zone Fix Round 3 verification

Reviewed: 2026-08-29  
Scope: scratch repair and full-ring reconciliation state machines only.

## Verdict

The two deterministic no-progress loops are closed in the current working
tree. All other review items remain outside Fix Round 3.

## Finding 1: restored PREPARED image cannot pass repair verification

`record_repair_preserve()` deliberately backs up a structurally valid record
whose sequence equals `s_next_sequence`, even when its commit marker is still
erased (`PREPARED`). The scratch image is restored byte-for-byte. The restore
verification path subsequently accepts only an `ACTIVE` record through
`flash_record_valid()`. Consequently the same valid PREPARED image is backed
up, restored, rejected, and scheduled for repair again. No transition owns the
required PREPARED-to-ACTIVE finalization after restoration.

Implemented root fix: runtime scratch validation accepts a structurally valid
PREPARED image only at `s_next_sequence`. Restore verification first proves
byte-for-byte equality with scratch, then writes the normal commit marker and
rereads an ACTIVE record before allowing repair to finish.

## Finding 2: stale ACTIVE at next slot is endlessly reconciled after wrap

Reconciliation starts at `s_next_slot` and adopts any valid ACTIVE record whose
sequence equals `s_next_sequence`. After a complete physical-ring wrap, a stale
ACTIVE image can occupy that slot while not being the current logical tail.
The current state machine has no terminal classification for this case: it
restarts reconciliation/adoption instead of reclaiming the stale physical
slot, so append can remain permanently pending.

Implemented root fix: after one complete physical-ring scan, the next slot is
reclaimed only when it is ACTIVE/PREPARED and its sequence is outside the
current live interval. It is tombstoned and routed through scratch-backed
sector repair; live records in that sector remain preserved.

## Automated evidence

- PREPARED repair RED: direct real repair exceeded 3000 recovery calls before
  the validation fix. GREEN: repair completes within the same bound, marker is
  ACTIVE, append is adopted once, and reboot exposes exactly one record.
- Full-ring RED: removing stale-slot reclamation exceeded 3000 reconciliation
  calls. GREEN: reclamation completes within the bound, append succeeds, FIFO
  contains only the new event, and reboot does not resurrect the stale event.
- Focused command: `python tools/tests/test_blind_zone_store.py`.

## Remaining external gate

BY25Q16ESMIG hardware fault injection is still required for real program/erase
timing and power cuts across scratch header, victim erase, restore, marker
finalization and scratch erase. Host evidence enforces NOR 1→0 and sector erase
semantics but is not a substitute for HIL.
