# Task5A report: SMS transaction and modem concurrency hardening

## Implementation

- Bound the default F39 SMS reply lifecycle to one static transaction. The
  sender, reply text, retry count, in-flight state, and RESET handoff are kept
  together until CMGS success or bounded retry exhaustion. New default-path
  SMS commands are rejected while that transaction is active, so a later
  sender cannot consume or replace an earlier RESET retry.
- Added one bounded RX byte/line demux for normal DMA draining and blocking AT
  waits. `+CMT` header/body lines feed the SMS ingress immediately. `+QIURC`
  and `+QIOPEN` received while an AT owner is held use a fixed four-entry
  deferred queue and are processed after ownership is released.
- Kept CMGS prompt and result handling owner-serialized, including exact
  `ERROR` and `+CMS ERROR` failure paths. SMS body lines are consumed as CMT
  payload and do not participate in AT response matching.
- Replaced GPS UART4 TXDE/TXC loops with a shared deadline- and watchdog-
  guarded writer, including a final TXC wait and bounded raw-frame failure.
- Added a fixed iteration guard to the HardFault emergency UART path; it does
  not depend on SysTick or watchdog service and remains lossy under a stalled
  debug UART.
- Kept the compact PARAM reply within the 192-byte SMS limit while retaining
  live ACC/GNSS fields. Host-only IMEI injection is limited to the production
  harness build.

## Verification

With GCC selected through `CC` and `REQUIRE_GCC=1`:

```
python tools/tests/test_ec800m_urc_demux.py   # PASS
python tools/tests/test_gps_tx_bounded.py    # C harness PASS
python tools/tests/test_f39_end_to_end.py    # PASS / PASS
python tools/tests/test_f39_actions.py       # PASS
python tools/tests/test_f39_config.py        # PASS
python tools/tests/test_f39_dualset.py       # PASS
python tools/tests/test_f39_parser.py        # PASS
python tools/tests/test_sms_transport_contract.py # PASS
python tools/tests/test_sms_ingress.py       # PASS
python tools/tests/test_sms_whitelist.py     # PASS
python tools/tests/test_sms_execute_boundary.py # PASS
python tools/tests/test_flash_config_migration.py # PASS
```

The aggregate `test_*.py` sweep also passed every Task5A/F39/SMS/GPS/AGNSS
script. `test_ext_flash_store_host.py` remains independently unable to build
its temporary FOTA stub because that fixture omits the `config_t` definition;
no Task5A file is involved. No target ARM build or hardware modem behavior is
claimed from these host tests.

## Scope and safety

Only Task5A production/test files are staged for this change. The six
pre-existing user-owned dirty files (`include/build_version.h`,
`include/i2c_accel.h`, `src/flash_config.c`, `src/hw_init.c`,
`src/i2c_accel.c`, and `src/jt808.c`) are intentionally excluded.
