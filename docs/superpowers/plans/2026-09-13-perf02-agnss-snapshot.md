# PERF-02 AGNSS verified read session

Goal: eliminate full-payload verification on every injection chunk, preserving
CRC32/SHA-256 validation and the existing persistent format.

Design: one internal, volatile verified metadata/slot snapshot. Open validates
both slots using the existing selection policy; repeated opens reuse the pinned
snapshot. Chunk reads check the pinned metadata under the flash owner lock and
retain workspace and range checks. Close, init, begin/write/commit/abort invalidate
the snapshot. No flash lock is held across main-loop iterations. Legacy get_latest
and read retain independent full verification. Only storage APIs may mutate AGNSS
regions; raw out-of-band payload changes during a session are outside this contract.

The manager opens/reuses a session, reads chunks, closes at completion/failure,
and includes payload CRC in its replacement detection. Full checks run again for
the next session. Sequence ordering remains the existing numeric ordering.

Alternatives: permanent per-slot caches cost more RAM and have a longer trust
lifetime; holding the flash owner for an entire injection would block OTA/others.

Implementation (C99, Python-driven host C harness):
- [x] Add a real storage + manager harness with a 1-to-0 NOR backend, read-byte
  counts, output equality, and a failing linear-I/O budget assertion.
- [x] Implement snapshot API in include/agnss_storage.h and src/agnss_storage.c;
  wire src/agnss_manager.c and update scheduler test stubs.
- [x] Cover bounds, dual slots, corruption, torn commit, initialization, owner
  contention, partial write/failure, retry, replacement, and repeated sessions.
- [x] Run AGNSS/flash regression, independent before/after Makefile builds,
  release/RAM gates, diff checks; document actual resource deltas and HIL limits.

No commits, deployment, flashing, or overwriting released artifacts.

Results: see docs/perf02-agnss-snapshot.md. Host tests/build pass; RAM and release
gates remain failed both before and after, so this is not release acceptance.
