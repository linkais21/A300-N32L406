# EC800M stability repair and App SHA consolidation

User approved the preceding proposal: fix RX DMA wrap first, then independently measure DUP-02. Execute inline; no commits, flashing, deployment, or overwriting archived images.

## Design and constraints
Use a single normalized DMA write-index snapshot at all RX consumption/discard sites. Remaining count zero maps to index zero; readers stay inside the 1024-byte ring. Keep DMA hardware mapping, buffer capacities, AT ownership, timeouts, RX ordering and watchdog policy. This repairs a reproducible software boundary, not proof of the field reset cause.
For DUP-02, share one incremental SHA-256 implementation between App FOTA and AGNSS with separate caller-owned contexts. Preserve all hash coverage, CRC/signature checks, Flash ownership and persistence. Boot remains independently linked and unchanged. Keep the consolidation only after correctness and final ARM size/stack measurement support it; do not weaken gates.
Existing worktree changes are required inputs. Store stage sources/build evidence separately in build/stability-sha-20260913. No release package until hardware acceptance; versions and archived images remain untouched for these engineering comparisons.

## Execution checklist
- [x] Freeze original changed inputs and build baseline with current Makefile in baseline/.
- [x] Add host test compiling actual ec800m.c: zero/reload, end-of-ring and wrapped byte ordering, AT response/prompt/QIRD timeout, stale-connect discard; bounded subprocess timeout. Demonstrate original failure.
- [x] Normalize all DMA snapshots in ec800m.c, run regression and ARM build into rx-fixed/; inspect flash and RAM gates.
- [x] Add SHA known vectors and chunk/boundary/interleaved-context tests; capture consolidation contract RED.
- [x] Share App SHA core; update Makefile and affected host link inputs; run SHA, AGNSS, FOTA, signature and ownership tests.
- [x] Build sha-shared/ with identical flags; compare BIN/static RAM/final stack against rx-fixed/; review full diff.
- [x] Document commands/results and HIL: long dual-TCP stationary soak, DMA wrap count, reset breadcrumbs, GPS drops, worst heap/stack; OTA/AGNSS remain separate acceptance.

Results: docs/stability-rx-sha-20260913.md. Required hardware acceptance remains pending; software work completed without changing release gates.
