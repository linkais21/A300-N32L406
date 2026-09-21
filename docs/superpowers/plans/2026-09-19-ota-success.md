# OTA success reporting

- User confirms stationary coordinate locking PASS; preserve its implementation.
- Actual platform contract is Python ota_platform: POST /api/device/updates/progress,
  X-OTA-Token, state=success. No platform deployment or hardware control in this task.
- Reuse CRC/commit-protected A/B checkpoint slots without wire-format or boot changes.
  Before PENDING, persist the complete download URL for reboot reporting. Recover old
  compact /d/token checkpoints too. Require ACTIVE BCR and running/checkpoint version
  equality; never report a trial, rollback or different version as successful.
- Share bounded READY transport for downloaded/success. Clear checkpoint only after
  HTTP 2xx, preserve on failure, three 15-second windows per boot with 60-second gaps.
  After the budget allow ordinary update checks; the next six-hour check cycle or
  a reset renews the report budget. The server's 48-hour token expiry is unchanged.
- Add real C host regressions first, covering HTTP failures, power/reset recovery,
  resource contention, duplicate invocation, mismatches and cleanup failure. Reuse
  byte-level NOR journal power-cut coverage and add report-specific assertions.
- Build separately, measure Flash/RAM, run OTA/boot/layout and locked-coordinate
  regressions, run release gate without waivers. Allocate a new local version before
  delivery; preserve all existing artifacts. Report hardware/platform validation gaps.
