# Task 4 report

Implemented resumable OTA Candidate handoff in `src/fota.c`.

- Added `fota_request_t`, `fota_status_t`, cancellation, and offset-aware chunk callback APIs.
- Added Resume/BCR checkpoint records with URL/ETag identity, expected length, offset, CRC/hash progress, and commit marker.
- Reconnects issue HTTP `Range: bytes=<offset>-`; duplicate chunks are verified against Candidate and out-of-order chunks fail safely.
- Candidate writes are serialized under `EXT_FLASH_OWNER_OTA`; timeout, size, identity, and write failures release the owner.
- Added dedicated EC800M OTA receive callback so OTA stream data is not routed to JT808.
- Added package/resume host replay tests.

Manifest verification now performs CRC32, payload SHA-256, product/hardware checks, and a fail-closed ECDSA hook. BCR serialization reuses `bootloader/include/bcr.h` and its exact packed layout/constants. HTTP headers are accumulated across modem reads; resumed transfers require a valid `206`/`Content-Range` response, while `200` safely restarts Candidate. Duplicate chunks are compared in full, in bounded blocks.

BCR `transaction_length` is the manifest payload length, excluding the manifest header.
`test_fota_package.py` includes a compiled runtime harness for the VERIFYING-to-BCR handoff; it captures the committed length and asserts it equals the payload length and not Candidate's manifest-plus-payload byte count. The source-level assertion remains as an additional guard.

The target application should provide a hardware-backed `fota_ecdsa_verify()` override. The default remains fail-closed.

Host tests pass. The repository environment did not provide `make`, so the embedded build could not be run here.
