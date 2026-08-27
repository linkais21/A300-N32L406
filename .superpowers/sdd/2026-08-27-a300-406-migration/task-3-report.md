# Task 3 implementation report

Implemented a compact, non-upgradable recovery bootloader scaffold for N32L406:

- 12 KB internal-Flash linker region with an 11 KB release-size assertion.
- Packed image manifest containing magic, product/hardware IDs, target/length,
  monotonic version, SHA-256, ECDSA signature bytes, and CRC32.
- Redundant A/B BCR records with sequence, CRC, commit marker, transaction
  offset, trial state, and boot-attempt accounting.
- Candidate verification hooks for complete download, bounds, identity,
  SHA-256, ECDSA, and anti-rollback checks.
- Transactional install/resume flow with LKG copy, page programming,
  readback verification, watchdog feed hooks, and LKG/Factory/recovery
  selection after three failed trial boots.
- Deterministic Python host model and tests for torn BCR writes, bad
  signatures, downgrade rejection, payload corruption, and three-boot
  rollback.

Verification performed:

```
python tools/tests/test_bcr.py              # PASS
python tools/tests/test_image_manifest.py   # PASS
gcc -std=c99 -Ibootloader/include -fsyntax-only \
  bootloader/src/bcr.c bootloader/src/image_verify.c \
  bootloader/src/image_install.c bootloader/src/main.c  # PASS
```

The ARM linker build remains toolchain-dependent; platform hooks are weak and
must be replaced by the SPI NOR, internal Flash, watchdog, reset-reason, and
ECDSA implementations during hardware integration.

## Round 1 review fixes

- Rollback now reads LKG/Factory manifests and payloads from external NOR and
  copies them page-by-page into internal application Flash with readback.
- BCR commits erase the selected NOR sector, write payload then marker, and
  require readback verification; CRC covers the canonical uncommitted marker.
- Reset handling increments Trial attempts; a healthy Trial can be committed
  ACTIVE through `bcr_mark_trial_healthy`.
- Resume reloads and verifies the Candidate manifest, persists target address,
  erases the target on a fresh transaction, and resumes page checkpoints.
- LKG backup stores metadata and uses the actual application-length hook.
- Recovery is a bounded watchdog-fed loop; product ID is A300/406 and weak
  platform hooks fail closed.

## Round 2 review fixes

- Explicit `ROLLBACK` handling restores verified LKG, then Factory, from NOR.
- External manifests now validate CRC, full payload SHA-256, identity,
  monotonic version, bounds, and ECDSA.
- LKG erase is required before metadata/payload writes and uses actual app
  length; BCR erase hooks fail closed and commits verify readback.
- Candidate/BCR target and length checks use subtraction-safe bounds.

## Round 3 review fixes

- LKG metadata now requires internal payload SHA-256, platform ECDSA signing,
  and CRC before it is written; unavailable signing fails closed.
- Resume requires BCR target/length to match the freshly verified Candidate and
  checks the persisted target bounds.
- External Candidate/LKG/Factory base plus manifest length is constrained to its
  assigned NOR region; restoration commits BCR ACTIVE and clears attempts.
- LKG erase length is sector-rounded with a region-size guard.

## Round 4 review fixes

- Resume now requires BCR image version to equal the Candidate manifest.
- Candidate target is fixed to the application base with subtraction-safe bounds.
- LKG/Factory recovery only jumps after a successful ACTIVE BCR commit; commit
  failure falls through to controlled recovery.
