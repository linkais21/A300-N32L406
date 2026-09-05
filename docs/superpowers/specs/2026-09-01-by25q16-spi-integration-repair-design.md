# BY25Q16ES SPI Integration Repair Design

## Goal

Restore reliable BY25Q16ES configuration persistence so a factory/default boot
can store the IMEI-derived PID and proceed to JT808 registration. When a Flash
operation fails, the UART log must identify the failing hardware stage without
printing device secrets.

## Evidence and constraints

- BY25Q16ES V2.6 specifies JEDEC ID `68 40 15`, SPI mode 0, `06H` Write Enable,
  `05H/35H/15H` status reads, `02H` Page Program and `20H` 4 KiB Sector Erase.
- Page Program must not cross a 256-byte page. Sector erase maximum time is
  300 ms and Page Program maximum time is 2.4 ms.
- The N32L40x vendor DATA_FLASH example configures the master MISO pin as
  `GPIO_Mode_Input`. The current application configures PA6 as `GPIO_Mode_AF_PP`.
- Existing external-Flash contents must not be erased except through the
  existing configuration transaction when that transaction is required.
- BP/CMP/SRP protection bits are diagnostic-only in this change. Firmware must
  not automatically rewrite non-volatile status registers.
- Existing user changes in `src/hw_init.c` and `src/flash_config.c` must be
  preserved.

## Design

### GPIO and initialization

Configure PA6/SPI1_MISO as `GPIO_Mode_Input`, matching the N32L40x master SPI
reference. Keep PA5/SCK and PA7/MOSI as AF push-pull and PA4/CS as software
push-pull output. At Flash initialization, drive CS high and ensure at least
1 ms has elapsed before the first selected transaction, satisfying BY25Q16ES
`tVSL` without relying on unrelated boot work.

Read and cache the complete 24-bit JEDEC ID. Initialization emits one bounded
line containing JEDEC and SR1/SR2/SR3 when communication succeeds, or a concise
failure line when it does not. No IMEI, PID, key or payload data is logged.

### Failure classification

The low-level driver records the most recent failure stage:

- `ID`: JEDEC mismatch or read failure.
- `READY`: status read failure or WIP timeout.
- `WREN`: WEL did not set after `06H`.
- `PROTECTED`: status protection bits indicate the requested array region may
  be protected.
- `ERASE`: the sector erase command or completion failed.
- `PROGRAM`: Page Program was not issued or did not complete.
- `VERIFY`: programmed bytes did not match read-back.

The existing public Boolean operations remain compatible. A small diagnostic
API exposes the last stage and status bytes to `flash_config.c`; this avoids
changing all Flash consumers.

`cfg_init()` reports whether default configuration persistence succeeded and
which slot/stage failed. It must continue using the existing redundant slot
transaction and must not mark a slot active before verification succeeds.

### Protection handling

Read SR1 (`05H`), SR2 (`35H`) and SR3 (`15H`). Report BP0-BP4/CMP/SRP-derived
protection state when a write or erase is rejected. Do not issue `01H`, `31H`
or `11H` and do not clear protection automatically. This keeps a field device's
protection policy intact.

## Testing

1. Add a source-contract regression test that fails while PA6/MISO is AF
   push-pull and passes only when it is an input.
2. Extend the host SPI harness to cover JEDEC/status reads, WEL rejection,
   protected erase classification, WIP timeout and successful program.
3. Extend the configuration harness to verify initialization logs persistence
   success/failure without weakening the power-cut transaction tests.
4. Run the focused Flash, configuration, identity and hardware-contract tests.
5. Run `make all`, `make release-guard`, `make ram-guard` and `git diff --check`.

## Hardware acceptance

After flashing the rebuilt application, a factory/default boot must show:

```text
[FLASH] JEDEC=684015 SR1=.. SR2=.. SR3=..
[CFG] defaults persisted slot=... gen=...
```

It must then stop printing `identity invalid reason=FLASH_WRITE`, emit the
one-shot identity diagnostic and send JT808 registration. If persistence still
fails, the new log must identify `ID`, `READY`, `WREN`, `PROTECTED`, `ERASE`,
`PROGRAM` or `VERIFY`. This final behavior requires real-device/HIL verification.

## Non-goals

- No automatic status-register modification.
- No Flash layout or persisted configuration format change.
- No factory reset, chip erase, firmware flashing, deployment or Git commit.
- No unrelated stack-budget or JT808 behavior change.
