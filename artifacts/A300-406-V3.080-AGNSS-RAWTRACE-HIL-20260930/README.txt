A300-406 V3.080 AGNSS raw-response diagnostic App, HIL ONLY.
Firmware identity: T360-A300_406_20260930154352,V3.080; version counter 3080.

The HEX starts at absolute App address 0x08006000. If using the BIN, set the
programming address to 0x08006000. This package contains no Bootloader or
Combined image. Direct App SWD programming bypasses OTA trial/rollback; use
one dedicated validation device. The version counter is still 3080, so this
is not a same-version OTA upgrade.

Continue recording the existing COM12 debug serial output from power-on.
After a first-frame BDS NAK, the firmware prints:
  [AGNSS-RAW] cold_to_tx=N tx_to_rx=N ms
  [AGNSS-TX] n=N data=<complete first BDS frame in hex>
  [AGNSS-RX] n=10 data=<complete 10-byte module response in hex>
  [AGNSS] result=0 ... reason=ack-nak ...
Save the full COM12 text/DAT file without truncating the long TX line. The
extra output occurs only after the NAK, so it does not alter the send/ACK
timing being measured. No separate UART4 capture equipment is required.

Flash used: 106276/106496 bytes, remaining 220 bytes. Flash and release
guards pass; whole-program RAM/stack evidence remains incomplete. This image
is for short, dedicated HIL diagnosis only and is not approved for release.
