# N32L406 HTTP OTA Integration Design

Date: 2026-09-09

## Objective

Connect the current A300-T9/N32L406 firmware to the current FOTA platform so an explicitly assigned device can discover, download, verify, install, confirm, or roll back an OTA release without a JT808 OTA command.

The device checks once after the modem and device identity are ready, then every six hours. After a complete package passes manifest, payload hash, and signature verification and the pending BCR is committed, the application immediately resets. The bootloader remains responsible for installation, trial boot, and rollback.

## Scope And Source Boundaries

The implementation targets are:

- Firmware: `D:\A300_406_tools\A300_406\A300-first`
- Platform: `D:\A300_406_tools\A300_406\fota-platform`

The following N32G452 sources are read-only references for bounded HTTP parsing, scheduling, retry behavior, and status transitions:

- `D:\A300_Tools\A300-N32G452\A300-N32G452\app\src`
- `D:\A300_Tools\A300-N32G452\A300-N32G452\app\ota_platform`

N32G452 Flash addresses, package headers, product IDs, hardware IDs, BCR records, binaries, and build inputs must not enter the N32L406 release pipeline.

## Resolved Contract Conflicts

Current repository evidence contains incompatible contracts:

- The platform README requires `X-Device-Key` and documents `FKEY,<key>#`.
- The platform filter currently exempts update checks and task downloads from authentication.
- The old protocol document and current platform image parser require a legacy 32-byte CRC32 package header.
- The N32L406 firmware already requires its signed `image_manifest_t`, SHA-256 verification, signature verification, BCR trial state, and rollback floor.

This design resolves those conflicts as follows:

1. The secured HTTP contract in the workspace instructions is authoritative.
2. Both update-check and download requests require `X-Device-Key`.
3. Firmware accepts `FKEY,<key>#` for a shared platform device key containing 16 to 31 printable ASCII characters.
4. The platform parses and stores N32L406 signed packages. It does not translate them into the legacy N32G452 format.
5. The platform check response contains only metadata needed to start the existing signed-package download. It does not replace device-side cryptographic verification.
6. OTA remains device-pull HTTP/1.1. No TCP 8800 service, JT808 `0x8108`, MQTT, gateway callback, or time-limited download token is added.

## HTTP Contract

### Check Request

After the EC800M data path and terminal identity are ready, the firmware opens a bounded short-lived HTTP connection and sends:

```http
GET /api/device/updates/check?deviceId=<11-digit-id>&deviceModel=A300-406&currentVersionCode=<u32> HTTP/1.1
Host: <configured OTA host>
X-Device-Key: <configured key>
Connection: close
```

The device ID uses the same canonical 11-digit identity already used by JT808. The current version code comes from a generated `FW_VERSION_COUNTER` build constant and is the same value embedded into the signed release manifest.

The platform returns a non-chunked JSON body with an exact `Content-Length`:

```json
{"updateAvailable":false}
```

or:

```json
{
  "updateAvailable":true,
  "versionCode":123,
  "downloadUrl":"http://fota.example/api/device/ota-tasks/<task-id>/download",
  "size":98765
}
```

An available update is valid only when all fields are present, `versionCode` is greater than the current version, `size` fits the external candidate partition, and the URL uses HTTP with the configured OTA host and port. Redirects and cross-host URLs are rejected.

### Download Request

The existing downloader continues to use a stable task URL and open-ended Range requests:

```http
GET <task-download-path> HTTP/1.1
Host: <configured OTA host>
X-Device-Key: <configured key>
Range: bytes=<checkpoint>-
Connection: close
```

The first request may omit `Range` when the persisted checkpoint is zero. A resumed request accepts only a valid `206` response whose `Content-Range` begins at the requested offset. A `200` response to a resumed request may restart from zero only after the candidate area is erased and state is reset. Chunked bodies, missing or inconsistent lengths, oversized headers and bodies, malformed ranges, redirects, and authentication failures are terminal for that attempt.

## Firmware Design

### Persistent Configuration

Append a device API key field without changing existing configuration prefixes. The persisted format version and migration logic must accept existing shorter records, zero-initialize the new tail, and preserve all current fields. The key is never printed in logs.

`FKEY,<key>#` validates the complete value before committing it. Values outside 16 to 31 printable ASCII characters are rejected without changing the active configuration. Query responses expose only whether a key is configured, not its value.

The existing `device_config_t.fota_url` field stores the OTA platform base URL for automatic checks, with product default `http://fota.lhhn.net`. It is independent of the main and backup JT808 servers. The existing `fota_start(url)` direct-download API continues to use its explicit URL argument and is not used by the automatic check scheduler.

### Version Identity

The release build takes one unsigned 32-bit `versionCounter`. The release tooling writes it into both:

- the signed N32L406 image manifest;
- generated firmware metadata as `FW_VERSION_COUNTER`.

Build and release guards fail if the generated current-version constant is absent, zero, or inconsistent with release metadata. Human-readable `FW_VERSION_STR` remains unchanged and is not parsed to make OTA ordering decisions.

### OTA Coordinator

The FOTA module gains bounded check states alongside its existing download states. It owns channel 1 only while a check or download transaction is active and continues using the shared service workspace and external Flash owner.

Scheduling rules:

1. Arm a boot check during initialization.
2. Start it only after the modem is ready, the canonical device ID is available, no trial-confirmation write is pending, and the OTA key is configured.
3. After any completed check, arm the next check for six hours later.
4. On transient transport or server failures, use a bounded retry count with increasing delay; after retries are exhausted, return to idle until the next periodic check.
5. Never spin, block the main loop, or retry without a deadline.

The check parser accepts only HTTP/1.1 success with bounded headers, JSON body size, exact `Content-Length`, expected content type, and no `Transfer-Encoding: chunked`. JSON extraction is order-independent, rejects duplicate or type-conflicting required fields, and does not log the device key or entire untrusted response.

### Download, Verification, And Apply

The update response feeds the existing resumable request structure. Download checkpoints remain bound to the complete URL and expected length. The downloader adds `X-Device-Key` to initial and resumed requests.

After all bytes are stored, the device validates:

- package total length equals manifest size plus image length;
- manifest magic, product ID, hardware ID, application target address, and bounds;
- manifest CRC;
- payload SHA-256;
- manifest signature;
- version counter against the rollback floor and advertised task version.

Only after all checks pass does the firmware commit `BCR_PENDING`. It then immediately resets. Failure before the BCR commit leaves the currently running application bootable and releases workspace and Flash ownership.

The existing bootloader and application trial-confirmation flow remains authoritative. A successful trial advances the rollback floor. A failed trial is rolled back by the bootloader.

## Platform Design

### Authentication

Remove the update-check and task-download exemptions from the device API key filter. Both endpoints return `401` for missing or invalid `X-Device-Key`, and return `503` when production device authentication is not configured. Constant-time key comparison is retained.

No secret value is returned by an admin API, logged, committed, or copied into tests. Tests inject a non-production key through test configuration.

### N32L406 Package Intake

Replace the legacy 32-byte package parser with an N32L406 manifest parser matching the firmware byte layout and byte order. Upload validation checks structural fields, package length, candidate-partition bounds, product/hardware identity, target address, manifest CRC, and payload SHA-256. The platform must verify the raw 64-byte ECDSA P-256 signature over the same canonical manifest digest used by the firmware, using a configured release public key that matches the firmware trust root. A missing, malformed, or mismatched public key makes signed-package upload unavailable and produces a configuration error.

The existing platform-generated RSA key pair is not compatible with the N32L406 trust contract. It must not sign, rewrite, or authorize N32L406 images. The platform stores no N32L406 release private key; signing remains an offline release-build operation.

The uploaded `versionCode` must equal `manifest.version_counter`. The device model is normalized to `A300-406`. The original signed bytes are stored and served unchanged.

To avoid a destructive production schema migration, existing storage columns are retained with an explicit N32L406 mapping: `body_size` stores `manifest.image_length`, `body_crc32` stores the manifest CRC32, `sha256` stores the manifest payload SHA-256, and `signature` stores the 128-character hexadecimal raw ECDSA signature. API fields and UI labels change from `bodyCrc32` to `manifestCrc32` and identify SHA-256 as the payload digest.

Legacy releases already stored with a 32-byte header or platform-generated RSA signature remain visible for audit but are not assignable to `A300-406` devices. Assignment revalidates the stored package under the N32L406 parser; operators must upload a signed N32L406 package before creating new tasks. Existing task records are not deleted or rewritten.

### Assignment And Status

Assignment stays whitelist-only. Publishing a release does not broadcast it to every device. A check request also records the device heartbeat and current version.

The platform returns a task only when its model matches and its target version is newer. Starting or finishing a servlet response does not prove that the modem received every byte, so the platform must not mark a task downloaded or terminal merely because it served a full object or final range. The same stable task URL remains downloadable across reconnects and old-version checks until the device later checks in at the target or newer version or an operator cancels the task. Old-version checks alone never close the task. A later check at the target or newer version marks success.

## Error Handling And Safety

- Authentication, malformed task metadata, version mismatch, wrong host, package overflow, invalid Range semantics, corrupt manifest, hash/signature failure, and BCR write failure never trigger reset.
- Logs contain state, status code, bounded lengths, version code, and failure category, but not API keys, full URLs containing secrets, response bodies, IMEI, ICCID, or precise location.
- OTA activity continues to block low-power entry so modem, RAM, and external Flash state are not lost mid-transaction.
- Watchdog service remains active through parsing, erase, hashing, signature verification, and BCR operations.
- The immediate-reset policy applies only after verified BCR commit. It intentionally does not wait for ACC state or vehicle motion.
- Platform deployment, production restart, firmware flashing, and real device commands are outside implementation authorization.

### Power-Loss And No-Brick Invariants

The following invariants are mandatory:

1. While checking or downloading, internal application Flash is never erased or programmed. A reset or power loss boots the existing application.
2. Download data is written only to the external candidate partition. A checkpoint is committed only after the corresponding candidate bytes have been written and read back successfully. Checkpoints use two independent sectors in the 64 KiB resume region, with sequence, CRC, and final commit marker; a new record is fully verified before the older valid slot is eligible for erasure.
3. After reboot, the device repeats the authenticated check, obtains the same stable task URL, validates its checkpoint identity and expected length, and resumes with `Range`. If the identity changed or the server cannot honor the range, it safely erases only the candidate partition and restarts from byte zero.
4. `BCR_PENDING` is committed only after the entire external candidate has passed manifest, hash, signature, version, and length validation. Network access is no longer required once this state exists.
5. Bootloader installation is an internal-Flash-page transaction. For each page, it erases that page, copies bounded chunks from the verified external candidate, reads back and verifies the whole programmed page, then atomically advances the dual-slot BCR offset to the next page. The BCR offset never points inside an uncommitted Flash page.
6. If power is lost during page erase, programming, verification, or BCR commit, the previous valid BCR slot remains usable. The next boot erases and rewrites the same page from the retained candidate before advancing.
7. The candidate package remains intact through installation and trial confirmation. It is not erased when the application first boots the trial image.
8. Trial failure restores a previously verified LKG image, then the provisioned factory image. Production acceptance requires a valid signed factory package to be present in its reserved external Flash partition; LKG and factory validity are checked before use.
9. If no bootable image can be proven, the Bootloader remains in a watchdog-serviced recovery state and never jumps to an invalid vector. This state is recoverable by service tooling but is not considered a successful field OTA outcome.

The current Bootloader advances `transaction_offset` in 256-byte copy chunks while internal Flash erasure is page-based. That behavior does not prove safe recovery from a torn program operation. This OTA integration therefore includes changing `install_resume()` to page-granular erase/program/readback/commit semantics and routing all candidate installation through that same resumable path.

Candidate preparation is also incremental: `fota_process()` erases at most one 4 KiB external sector per call, services the watchdog, and returns to the main loop between sectors. It erases only the sector-rounded advertised package range, or only the uncommitted tail when resuming, rather than blocking while erasing the full 448 KiB partition.

## Verification

Firmware automated verification must cover:

- valid and invalid `FKEY` persistence and migration;
- boot check gating and six-hour rearm;
- check parser fragmentation, coalescing, field order, duplicates, malformed JSON, missing length, chunked response, oversized input, non-200 response, and timeouts;
- authenticated initial and resumed GET requests without secret logging;
- no update, downgrade, wrong model/host/port, oversized package, advertised/manifest version mismatch, interrupted download, retry exhaustion, and checkpoint resume;
- torn writes at both download-checkpoint slots, proving that at least one prior valid checkpoint survives;
- verification success commits BCR before reset;
- every verification and storage failure avoids reset and releases resources;
- existing trial confirmation and rollback behavior;
- Bootloader power-cut injection before and after page erase, each page program, readback verification, and both phases of the dual-slot BCR commit;
- repeated reset at every download checkpoint and every installation page boundary, proving monotonic recovery without dependence on the network during install;
- ARM build, release guard, RAM guard, focused host tests, full relevant host suite, and `git diff --check`.

Platform automated verification must cover:

- missing, invalid, and valid device key paths for check and download;
- no task, assigned task, model mismatch, downgrade suppression, success inference, and operator cancellation;
- interrupted full and Range responses remain downloadable and are not falsely made terminal by server-side response creation;
- N32L406 manifest field validation, length/bounds, CRC, SHA-256, signature, and version consistency;
- exact `Content-Length`, no chunked transfer, full download, valid ranges, invalid ranges, stable URL, and unchanged signed bytes;
- backend `mvn verify`, frontend `npm run build`, configuration rendering where environment prerequisites exist, and `git diff --check` where the directory is a Git worktree.

Hardware/HIL acceptance remains required for EC800M fragmented HTTP reception, server authentication, interrupted Range resume after modem and MCU resets, external Flash persistence across reset, immediate reset after verification, power interruption during internal Flash erase/program, bootloader install continuation without network, trial confirmation, LKG restore, factory restore, and forced rollback. A production device cannot be accepted as no-brick capable until its factory partition has been read back and cryptographically verified.

## Acceptance Criteria

1. A device without a configured valid key cannot obtain task metadata or firmware bytes.
2. A keyed, whitelisted `A300-406` device reports the exact current manifest version and receives only a newer compatible task.
3. The device can resume an interrupted signed package and rejects inconsistent server responses.
4. A valid package is stored unchanged, cryptographically verified, committed as pending, and followed immediately by reset.
5. An invalid or incompatible package never changes the boot target and never triggers reset.
6. After a healthy trial boot the platform observes the new version and marks success. After a rollback the old application remains bootable and the task remains nonterminal and downloadable until an operator diagnoses and cancels it; the platform does not claim rollback from ambiguous HTTP delivery evidence.
7. Existing JT808 reporting, sleep admission, Flash ownership, and prior `0x0107`/`0x0200` behavior remain covered by regression tests.
8. Power loss or reset at every modeled download and installation cut point converges to the old application, the fully installed new application, or a verified rollback image; it never jumps to a partial or unverified application.
9. Network loss during download preserves resumable progress, while network loss after `BCR_PENDING` does not prevent offline installation from the verified candidate.
10. A partial HTTP response followed by any number of old-version checks does not revoke the stable task URL or prevent the device from resuming.
