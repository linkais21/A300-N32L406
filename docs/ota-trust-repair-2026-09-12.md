# OTA signature failure: diagnosis and repair

## Confirmed cause

The supplied September 12 serial capture runs V3.034, accepts V3.035, downloads
105808 bytes and fails at `install failed stage=signature`. In production
`fota_verify_manifest`, this branch follows successful whole-package SHA-256
comparison and precedes authorization/BCR PENDING writes.

The live platform check response was read during diagnosis. Its public fields
are preserved in `tools/tests/fixtures/platform_v3035_signature.json` without
device identities, network addresses, tokens or private keys. Its digest equals
the archived `artifacts/V3.035/A300-406-OTA-V3035.bin` digest.

Independent P-256 verification of that response:

| Public key | Result |
| --- | --- |
| Former L406 key, X starts `d90bf067` | Reject |
| User-provided G452 reference Bootloader key, X starts `b62d2b71` | Accept |

The former header's statement that this second key was wrong is contradicted
by live signature verification. Neither key verifies the archived V3.023
signature text; that historical record must not be used as a trust anchor.

## Reference comparison and chosen change

The G452 App checks downloaded SHA/CRC and passes the detached signature to its
Bootloader. Its Bootloader uses secp256r1 and the 64-byte big-endian `r || s`
signature over SHA-256 of the complete package. This matches the L406 contract.
L406 retains its stronger pre-install App signature check and Bootloader check.
Only the incorrect public key is replaced, using the reference key and live
signature as independent evidence. No private key, HTTP API, image format,
Flash address, rollback policy or signature rejection rule is changed.

Both modem implementations defer receive work and bound their read passes.
L406's existing QIRD implementation already completed this download with a
matching SHA-256. The reference driver's MCU configuration is not transplanted.
The modem replay fixture now models the existing QIRD counter query, deferred
read pass and READY identity prerequisites; payload assertions remain intact.

## Build and regression protection

App verifier/FOTA and Bootloader verifier/image verification objects now depend
on the trust header. Previously, changing that header could leave stale key
bytes in incremental builds. A Make dry-run regression proves those objects
are rebuilt after a simulated header update.

`platform-trust-guard` is included in `make release-gate`. The versioned release
builder also runs the actual platform signature test before generating outputs.
The test uses the shipped header, actual micro-ecc C implementation and portable
32-bit arithmetic, plus a 64-bit cross-check and tamper rejection.

From the firmware repository:

```powershell
python tools/tests/test_platform_trust_anchor.py
python tools/tests/test_trust_key_build_dependency.py
python tools/tests/replay_platform_signed_ota.py --package artifacts/V3.035/A300-406-OTA-V3035.bin --metadata tools/tests/fixtures/platform_v3035_signature.json
python tools/tests/test_fota_platform_flow.py
python tools/tests/test_fota_resume.py
python tools/tests/test_fota_checkpoint_powercut.py
python tools/tests/test_ec800m_urc_demux.py
python tools/tests/test_fota_modem_handoff.py
```

The full signed replay links production App OTA, SHA/CRC, NOR journal,
micro-ecc and Bootloader verification. Hardware is simulated. Valid input
reaches authorization, PENDING, Bootloader acceptance and bounded reset;
tampered signatures/bytes are rejected. It does not execute an MCU flash
installation or prove actual device boot behavior.

## Device repair and release constraints

1. Allocate a new release version above 3035 and reconcile the existing version
   metadata/release guard baseline before packaging. Never overwrite V3.034 or
   V3.035 archives. The diagnostic build in `build-ota-trust-20260912` retains
   the working-tree version and is not a newly registered release.
2. Back up device configuration and recovery state, then install a reviewed
   complete App + Bootloader repair using SWD. Do not erase external Flash or
   device configuration as an attempted signature fix.
3. Build the subsequent higher-version OTA target with the same corrected key,
   upload it through the normal platform signing flow, and assign it to a test
   device. Do not use archived V3.035 as the final target: its App embeds the
   old incorrect key and would reintroduce the next-upgrade failure.
4. Require `authorized`, `pending`, target-version boot and TRIAL-to-ACTIVE
   confirmation. Exercise interruption/recovery and a second successful OTA.
   GPIO, Flash, watchdog and installation behavior require real-device/HIL
   verification. No server write, device control or flashing was performed.

## Verification and follow-up release

The user subsequently requested a paired validation release. V3.036 (complete
SWD repair) and V3.037 (OTA target) are now archived. Both passed their release
gates and artifact verification before delivery. See
[`../artifacts/OTA-TEST-V3036-V3037/README.md`](../artifacts/OTA-TEST-V3036-V3037/README.md).

Fresh build/guard commands (the local `make.cmd` cannot locate make in this
workspace, so the installed executable was used directly):

```powershell
../tools/w64devkit/w64devkit/bin/make.exe all BUILD=build-ota-trust-20260912
../tools/w64devkit/w64devkit/bin/make.exe -C bootloader -B all
../tools/w64devkit/w64devkit/bin/make.exe -s ram-guard stack-guard platform-trust-guard BUILD=build-ota-trust-20260912 STACK_AUDIT_BUILD=build-ota-trust-20260912/stack-audit
python tools/map_ram_guard.py bootloader bootloader/build/bootloader.map
python tools/release_guard.py
python tools/tests/test_feature_guards.py
```

App binary size is 105776 bytes; Bootloader binary size is 12312 bytes. Both
were inspected and contain the corrected key exactly once and no former key.
App static RAM is 17820 bytes; the audited FOTA process frame is 776 bytes.
The regression suite also passed generic ECDSA, JSON parsing, package/layout,
Bootloader fail-closed and invalid-vector recovery, legacy signature checks,
90 LKG operation cuts, 25715 checkpoint byte cuts and 4803 authorization cuts.
The modified-file `git diff --check` passed.

The App and Bootloader compile, and RAM/stack guards pass. During the initial
diagnosis, the release guard rejected three pre-existing identity inconsistencies:
`release_identity.json`, `include/config.h`, and `include/build_version.h`.
The contract said V3.035/3035 but `firmware_revision` was 33, and the release
identity test still pinned V3.022. For the requested releases, version fields,
the pinned test and the reviewed identity digests were synchronized for each
new version; the final source state is V3.037. No gate was removed or bypassed.
The feature guard's reference-platform comment match was resolved by linking
to this document instead, without changing modem behavior. Both gates now pass.
The earlier diagnostic build remains unversioned validation evidence, not a
release image; use the new paired delivery for the hardware test.

## Files changed by this repair

- `include/trusted_public_key.h`: corrected shared key and evidence comment.
- `Makefile`, `bootloader/Makefile`: trust dependencies and release trust gate.
- `tools/build_dev_release.py`: actual-key verification before packaging.
- `tools/tests/test_platform_trust_anchor.py` and
  `tools/tests/fixtures/platform_v3035_signature.json`: actual platform vector.
- `tools/tests/test_trust_key_build_dependency.py`: incremental rebuild check.
- `tools/tests/replay_platform_signed_ota.py` and
  `tools/tests/test_fota_platform_flow.py`: real App/Bootloader crypto replay.
- `tools/tests/test_ec800m_urc_demux.py`: repair outdated modem simulation.
- `README.md` and this document: repair, validation and release constraints.

Unrelated working-tree changes and original release archives were preserved.
