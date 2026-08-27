
# Task 6 report
Implemented explicit Huada F1D9 framing/validation for TAU804M and Zhongkewei request/response helpers for ATGM332D-F7N. Added bounded gps_send_raw, provisioning credentials in flash config, AGNSS callback integration, and host protocol tests. Credentials remain runtime-configured; malformed frames are rejected.

Round 1 hardening removed the weak duplicate vendor symbol, made the callback
signature consistently bool, added bounded Huada stream buffering with an
explicit zero-length flush, removed the legacy ATGM332D alias, selected the
receiver from persisted `gnss_type`, and registered EC800M channel-2 AGNSS
delivery. The supplied Zhongkewei document exposes the ASCII key/value request
and says the response is a server header followed by receiver binary data, but
the extracted document does not contain a complete machine-readable header
layout; the parser therefore fails closed unless its documented length/check
fields are present.

Round 2 adds explicit `INCOMPLETE`/`OK`/`MALFORMED` response classification,
bounded fragmented buffering for Zhongkewei, immediate discard on bad magic,
length, status, or checksum, and checks the Huada zero-length flush result
before the manager marks injection complete. Channel-2 network bytes are now
forwarded to the selected vendor stream parser and rejected while OTA is
active. The Zhongkewei binary response envelope remains intentionally
fail-closed: its exact on-wire header/checksum layout has not been confirmed
from original vendor material or a packet capture.
