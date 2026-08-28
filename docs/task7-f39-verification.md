# Task7-F39 host verification

Date: 2026-08-28
Verified base: `7a525ab6ba8fd1f55ab2b2e407a3eb0503734f3b`
Task 6 guard review base: `77d78b6face005ec43bc02d67ae18930e72c50fd`

## Verdict

Task7-F39 and Task5A host behavior is substantially covered, but this is not
a release approval. The complete `REQUIRE_GCC=1` host sweep produced **24
PASS, 1 FAIL, 0 SKIP**. The one failure is an existing external-Flash/FOTA
test-fixture compile defect, not a passing test and not a Task7/Task5A
production failure. Target build, SRAM/map and hardware gates remain open.

The release is additionally blocked by two repository-level gaps found during
verification:

- `tools/release_guard.py` fails on three existing `T663B` matches
  (`src/main.c`, `src/jt808_params.c`, and the user-owned dirty
  `include/build_version.h`). The authoritative runtime `FW_VERSION_STR` does
  equal the requested target, but the repository release guard is not green.
- The external-Flash blind-zone address, size and owner are preserved, but no
  production blind-zone location write/replay implementation is present under
  `src/` or `include/`. Layout preservation is verified; functional replay is
  not verified and must not be claimed.

Task 6 did not change production code.

## Host test evidence

All scripts were run individually with `REQUIRE_GCC=1` and the available host
GCC. There were no compiler-unavailable skips.

| Area | Script | Result |
|---|---|---|
| F39 parser | `test_f39_parser.py` | PASS |
| F39 config | `test_f39_config.py` | PASS |
| Flash config v1/v2 migration | `test_flash_config_migration.py` | PASS |
| Atomic DUALSET | `test_f39_dualset.py` | PASS |
| F39 actions and bounded replies | `test_f39_actions.py` | PASS |
| `+CMT` to F39 execution/reply | `test_f39_end_to_end.py` | PASS (both harnesses) |
| EC800M URC demux/concurrency | `test_ec800m_urc_demux.py` | PASS |
| GPS bounded UART TX | `test_gps_tx_bounded.py` | PASS |
| SMS whitelist | `test_sms_whitelist.py` | PASS |
| SMS ingress | `test_sms_ingress.py` | PASS |
| SMS execution boundary | `test_sms_execute_boundary.py` | PASS |
| SMS transport contract | `test_sms_transport_contract.py` | PASS |
| RAM guard model | `test_ram_guard.py` | PASS |
| Feature/platform guard | `test_feature_guards.py` | PASS |
| FOTA package/auth contract | `test_fota_package.py` | PASS |
| FOTA resume contract | `test_fota_resume.py` | PASS |
| Boot control record | `test_bcr.py` | PASS |
| Image manifest | `test_image_manifest.py` | PASS |
| External-Flash layout | `test_ext_flash_layout.py` | PASS |
| External-Flash store/FOTA lock host | `test_ext_flash_store_host.py` | **FAIL** (fixture compile) |
| AGNSS scheduler/OTA priority | `test_agnss_scheduler.py` | PASS |
| AGNSS storage | `test_agnss_storage.py` | PASS |
| AGNSS vendor stream | `test_agnss_vendor_stream.py` | PASS |
| Huada F1D9 | `test_huada_f1d9.py` | PASS |
| Zhongkewei AGNSS | `test_zhongkewei_agnss.py` | PASS |

### Existing external-Flash host fixture failure

`test_ext_flash_store_host.py` fails before its FOTA lock assertion can run.
The temporary shim does not expose `FLASH_TOTAL_SIZE` and
`FLASH_SECTOR_SIZE` to the real `ext_flash_store.c` or harness, does not
provide the now-required `flash_config.h`, and the harness uses `config_t`
without including its temporary `config.h`. GCC reports those missing macros,
the missing header and unknown `config_t`.

The test was introduced by `b5e8eed432370829faf73e96d717f8123f03ff69`
and has not been changed from that commit through the verified base. Its
independent `test_owner_bounds_alignment_and_error_propagation()` harness was
run alone and passed. This localizes the recorded FAIL to the stale FOTA shim;
it does not turn the unexecuted FOTA assertion into a PASS. Task 6 was not
authorized to edit this test.

## Static contracts and preservation audit

- Exact F39 roots: PASS. The production parser table contains exactly
  `PARAM`, `DUALSET`, `RESET`, `PID`, `IP`, `FIP`, `FREQ`, `HBT`, `MODEL`,
  `SPEED`, `APN`, `RELAY`, `GPSDUP`, `MLG`, `CAR`, `GPSBDS`, and `GMTSET`.
  The ingress base-root table contains the same set except `DUALSET`, which is
  handled explicitly and validates its nested root.
- Bounds: PASS. `F39_COMMAND_MAX_LENGTH` is 191 bytes, parser storage is 191
  bytes, `SMS_COMMAND_MAX_LEN` is 192 bytes, queue-entry storage is 192 bytes,
  and ingress rejects `len >= 192`. Parser tests cover valid 191 and rejected
  192 byte inputs.
- FIFO: PASS. `SMS_QUEUE_DEPTH` is exactly two and host ingress/whitelist tests
  exercise the bounded queue.
- Version target: PASS for the authoritative runtime value:
  `T360-A300_406_20260823000000,V3.000` in `include/config.h`. This does not
  waive the separate failing repository release guard described above.
- OTA preservation: PASS at source/layout/host-contract level. `src/fota.c`
  remains in the release build; Candidate and Resume/BCR mappings remain tied
  to `EXT_FLASH_CANDIDATE_*` and `EXT_FLASH_RESUME_ADDR`; FOTA, BCR, manifest,
  resume and layout tests pass.
- Blind-zone preservation: PASS only for the external-Flash partition and
  owner contract (`0x110000`, 644 KiB, `EXT_FLASH_OWNER_BLIND_ZONE`) and their
  non-overlap assertions. Functional blind-zone write/replay is absent and
  therefore remains a release blocker.
- Removed feature scan: PASS in release production inputs. Tests and docs are
  deliberately outside the scan so negative assertions may name removed
  features.
- N32G452 platform contamination scan: PASS for the exact release production
  inputs selected by the application Makefile. The guard parses `SDK`,
  `C_SRCS`, and `INCLUDES`; it scans the 15 selected SDK `.c` files
  (`system_n32l40x.c` plus the 14 listed peripheral-driver translation units)
  and all 38 headers under the three selected SDK include roots, in addition
  to project/bootloader source, headers, startup, linker and Makefile inputs.
  None contains `N32G452`, `N32G45x`, or `N32G4xx`. A temporary-tree negative
  regression injects each forbidden form into a derived compiled SDK source
  or SDK include header and proves it is reported. Unrelated vendor example
  projects are deliberately excluded because the Makefile neither compiles
  them nor adds their directories to the include path; historical N32G45 text
  in those examples is not classified as release-input pollution.

## User-owned dirty files

The following six pre-existing files remain modified and unstaged after Task
6, with the same current patch sizes observed before verification:

| File | Added | Deleted |
|---|---:|---:|
| `include/build_version.h` | 5 | 4 |
| `include/i2c_accel.h` | 2 | 1 |
| `src/flash_config.c` | 1 | 0 |
| `src/hw_init.c` | 2 | 2 |
| `src/i2c_accel.c` | 44 | 4 |
| `src/jt808.c` | 45 | 14 |

Across `2773148^..7a525ab`, only the prerequisite schema commit `ba99189`
modified one of these paths (`src/flash_config.c`). Inspection confirms its
committed migration hunks did not include the user's
`.gnss_type = GNSS_TYPE_TAU804M` hunk; that exact hunk remains unstaged.
None of the other five dirty paths appears in the Task7/Task5A commit range.

`git diff --check` passed for the complete working tree before the Task 6
commit.

## Explicit Task10 release gates

The following evidence is still mandatory. Host tests do not satisfy it:

1. Build the application and bootloader with the target ARM toolchain; record
   all warnings and require the approved warning policy to pass.
2. Inspect the real linker map and enforce the 24 KiB SRAM budget, including
   static RAM, stack margin and worst-case concurrency.
3. Exercise real EC800M-CN SMS operation: CNMI setup, fragmented `+CMT`, CMGS
   prompt/result/error/retry, stale URCs and two senders.
4. Stress modem ownership with JT808, OTA/FOTA, SMS and AGNSS traffic active;
   prove no URC loss, response theft or unbounded wait.
5. Inject UART4 faults (stalled TXDE/TXC, partial frames and receiver reset)
   and prove bounded GPS transmit failure plus watchdog service.
6. Execute OTA power-cut and rollback matrices: download/resume, verify,
   pending BCR, install, Trial failures, LKG and Factory fallback.
7. Verify blind-zone write/replay on external Flash after its missing
   production implementation is resolved.
8. Run watchdog, low-voltage/brownout and extended hardware soak testing,
   including recovery diagnostics and Flash/modem/GNSS contention.
