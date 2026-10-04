# V3.078 RAM-01 production audit

The V3.078 App image remains unchanged by this audit. Its packaged `App-V3078.bin`
SHA-256 is `ecd63200e162e333c6644cb11ff43130bf7c8184203264adf402388e9318770a`.
The diagnostic build and the production device both report V3.078, but a serial
version string alone does not bind a device to this exact image hash.

## Final-link budget

From `build/a300_firmware.map`, `stack-evidence.json`, and `stack-analysis.json`:

| Item | Bytes |
| --- | ---: |
| N32L406 SRAM | 24,576 |
| `.data + .bss` | 17,236 |
| Linker alignment before `_end` | 4 |
| `_end` to `_heap_limit`, maximum permitted heap | 1,024 |
| Longest currently resolved main call-frame chain | 2,632 |
| Remaining after these obligations | 3,680 |
| Required runtime gap | 4,096 |
| Necessary budget shortfall | 416 |

This calculation is conservative about the heap: the observed heap use is zero,
but `_sbrk` can allocate up to `_heap_limit`. The shortfall is a failure of the
worst-case budget, not evidence of a measured memory collision. Additional IRQ,
library, indirect-call, and fault frames have not been included. The analyzer
still reports 68 missing frames, 66 indirect transfers, 129 tail transfers,
two internal calls, and one reachable cycle. The release gate must remain closed.

`tools/map_ram_guard.py` now reads the final MAP heap symbols and rejects this
necessary shortfall directly. Its regression was red before the change and
green afterward. `tools/tests/test_ram01_frame_budget.py build` now fails on
the same 3,680-byte remainder, instead of reporting a pass that ignores the
hard heap reservation.

## Available device evidence

The partial COM12 V3.078 capture dated 2026-09-28 10:20 contains 26 `HEALTH`
samples: maximum `HEAP_USED=0`, maximum `STK_PEAK=2384`, minimum
`RAM_GAP=4952`, and all `F=0`. It also records a successful AGNSS online
injection. This capture does not include the complete OTA interruption stress
sequence and cannot establish a whole-program peak. The user's separate OTA
success and power/network interruption recovery observations are functional
evidence, not RAM bounds.

## Closure conditions

1. Reduce static storage and/or the longest executable stack chain enough to
   cover at least the 416-byte necessary shortfall plus audited IRQ, library,
   and fault-frame costs. Keep the 1,024-byte hard heap contract and 4,096-byte
   gap unless a separately reviewed contract change proves a different bound.
2. Resolve the analyzer's reachable frame, indirect-transfer, tail-entry, and
   cycle obligations; prove bounded interrupt nesting and heap behavior.
3. Rebuild a new version after any firmware change, run `make release-gate`
   and the host regressions, then validate that exact binary on hardware.

No existing production image or package was overwritten. No device was flashed.

An isolated `f39_prepare_config` noinline trial made the known chain 2,688 B
and the App 105,260 B, both worse than baseline. The source experiment was
removed. The normal build was relinked and its App SHA-256 matched the packaged
V3.078 hash above exactly. The trial output is marked `DO_NOT_FLASH.txt`.

Verification: `test_lto_stack_guard.py` (13 tests), `test_ram_guard.py`,
`test_heap_bounds.py`, `test_flash_capacity_guard.py` (10 tests), and
`test_flash_gate_build.py` passed. `make release-gate` failed at the expected
RAM budget, with `remaining_after_heap=3680` and `required_gap=4096`.

The standard release builder previously selected a local `make.CMD` wrapper.
Its batch-block `%errorlevel%` expansion could return success after the real
make had failed; the builder's separate App RAM check still stopped this
release attempt. `tools/build_dev_release.py` now selects the workspace's real
`make.exe` and rejects batch wrappers. `test_release_make_selection.py`,
`test_dev_release_manifest.py`, and `test_build_version_refresh.py` passed.
This is a build-tool correction, not a RAM-budget waiver.

## Unreleased RAM candidate

An isolated build at `build-ram-candidate-v3079/` has a `DO_NOT_FLASH.txt`
marker. It still identifies itself as V3.078 and is not a versioned release.
The source candidate retains four deferred socket URC slots but sizes each at
64 bytes instead of 256. Supported `+QIOPEN` and `+QIURC` forms fit; an
oversized malformed line is rejected rather than truncated into a valid event.
The dequeue copy also uses a 64-byte stack array.
The configuration query uses bytes 384 through 574 of its already owned
1024-byte service workspace for its 191-byte command; the 384-byte receive
region and final 16-byte asynchronous request region remain separate.
The blind-zone replay encoder now writes the outbound body into the record
array after `blind_zone_peek` completes. Compile-time offset/size assertions
protect the forward in-place transform; the host replay test compares every
item in the wire body and includes maximum-length location records.

The candidate MAP reports static RAM 15,968 B, down 1,268 B from the original
17,236 B. The resolved main call-frame chain is 2,544 B, down 88 B. With
the unchanged 1,024-byte heap reservation, the necessary remainder is
5,036 B, or 940 B above the 4,096-byte runtime gap *before* IRQ and unknown
frames. The App load span is 105,220/106,496 B. `make ram-guard` still fails:
68 missing frames, 66 indirect transfers, 129 tail transfers, two internal
calls, one cycle, and IRQ/fault nesting have not been bounded. This candidate
does not close RAM-01 and must not replace the production image.

The deferred-URC reentry test was red on the original 256-byte queue and
passes with the candidate, including queue capacity, stale-generation,
nested-wait, maximum QIOPEN error and PDP deactivation cases. The config
query lifetime and F39 integration tests pass. This does not establish
whole-program stack safety or OTA/AGNSS HIL behavior for the candidate.

Final candidate verification: `make all BUILD=build-ram-candidate-v3079`
passed; `test_ram01_frame_budget.py` passed the necessary budget;
`test_ec800m_stack_reentry.py`, `test_ec800m_urc_demux.py`,
`test_ec800m_dma_wrap.py`, `test_ec800m_udp_transaction.py`,
`test_ec800m_udp_wire.py`, `test_cfg_query_pass.py`,
`test_cfg_query_lifetime.py`, `test_cfg_query_f39.py`,
`test_f39_end_to_end.py`, `test_blind_zone_replay.py`,
`test_blind_zone_ack_channel.py`, `test_fota_platform_flow.py`,
`test_fota_resume.py`, and `test_agnss_online.py` passed.
`make release-gate BUILD=build-ram-candidate-v3079` failed as intended at
the incomplete stack-evidence check. `git diff --check` passed for changed
source and tests. The existing `build/a300_firmware.bin` SHA-256 still equals
the V3.078 image hash at the top of this record. No package was produced.

After this audit, a separate V3.079 test-only App and OTA image were built in
`artifacts/A300-406-V3.079-RAM-HIL-TEST-ONLY-20260928/` for a dedicated unit.
Its package README and SHA256SUMS identify the exact bytes. This does not
change the RAM-01 release decision or the V3.078 production image.
