# V3.095 mileage precision repair and firmware delivery

Authorized: repair incremental mileage loss and generate local flashing/OTA
files. Preserve existing changes and old packages. No commits, flashing,
platform upload or deployment.

1. Preserve starting inputs, touched-file backups and old package hashes.
2. Add a real-C fractional-mileage regression; record RED against original code.
   Cover sub-metre/ordinary movement, duplicate samples, rejected jumps,
   stationary locks, invalid fixes and restart behavior.
3. Carry accepted millimetres in bounded RAM and add completed metres only.
   Keep acceptance rules, Flash/config format and JT808 units unchanged.
   Retain earned fractions across stops; reboot loses less than one metre of
   remainder. Existing unflushed whole-metre power-loss limits remain.
4. Verify the repair, review the scoped diff, allocate V3.095/3095 and synchronize
   identity contracts and their audited fingerprints.
5. Build App/Bootloader with production Makefiles and ARM GNU 14.3.1 in
   build-v3095-delivery. Enforce App <=106496 B and complete runtime gap >=4096 B,
   release-gate and platform trust; do not relax limits.
6. Run relevant mileage/GNSS/JT808/persistence/OTA/Bootloader/release regressions;
   preserve commands, results, source identities and failure resolutions.
7. Generate Combined HEX/BIN, App/Bootloader and platform-detached OTA transport
   in a new V3.095 directory. Verify vectors, addresses, version, CRC, payload,
   HEX/BIN equality, file SHA256 and ZIP integrity.
8. Deliver Chinese usage and HIL scenarios. Explain Combined factory-init,
   normal OTA config retention, no historical mileage backfill, and required
   real-device road/HIL verification.

Workbook evidence: 1128 valid realtime points yield approximately 73.413 km;
reported daily odometer increase is 70.600 km. Sparse export does not establish
that all 2.813 km comes from truncation. Do not distribute identifiers or tracks.
