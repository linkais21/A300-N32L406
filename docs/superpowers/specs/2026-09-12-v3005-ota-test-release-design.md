# A300 V3.005 OTA Test Release Design

## Goal

Create a V3.005 OTA test release from the same current firmware source used for
the existing V3.004 release. The release exists only to test an upgrade from a
device programmed with V3.004 to V3.005.

## Scope

- Change the release revision from 4 to 5.
- Change the full firmware version suffix from `V3.004` to `V3.005`.
- Change the numeric OTA version counter from `3004` to `3005`.
- Update version-specific documentation and contract-test expectations.
- Generate a new immutable `artifacts/V3.005/` release directory.

No firmware feature, protocol, configuration, Flash layout, bootloader logic,
or OTA behavior will be intentionally changed. Existing user changes in the
working tree are preserved.

## Release Outputs

The release builder will produce the normal N32L406CBL7 artifact set, including:

- `Combined-N32L406CBL7.bin` for full wired programming.
- `App-N32L406CBL7.bin` for App-only wired programming.
- `A300-406-OTA-V3005.bin` for upload to the FOTA platform.
- ELF, HEX, MAP, Bootloader, checksum, size, vector, toolchain, Git revision,
  and dirty-worktree metadata artifacts.

The existing `artifacts/V3.003/` and `artifacts/V3.004/` directories remain
unchanged. The V3.005 builder must fail instead of overwriting a pre-existing
`artifacts/V3.005/` directory.

## Verification

Before delivery:

1. Demonstrate the existing version-contract test rejects the V3.005 target.
2. Update the contract and demonstrate the focused version tests pass.
3. Run the OTA/FOTA host tests relevant to version comparison, package format,
   download/resume, modem handoff, and platform flow.
4. Run the release build, release guard, RAM guard, stack guard, and firmware
   build checks required by the repository.
5. Validate the V3.005 manifest, artifact hashes, OTA header version `3005`,
   and the embedded runtime version string.
6. Run `git diff --check` and review the scoped differences.

The generated manifest is expected to record `git_dirty: true` because the
current V3.004 source contains user-owned uncommitted changes.

## External Validation

No platform upload, deployment, device programming, or remote-control command
is performed. Final acceptance requires real-device/HIL verification: program
V3.004, publish the V3.005 OTA package for the matching device/product, observe
automatic check/download/reboot, confirm V3.005 runtime identity, and verify
rollback/recovery behavior if the upgrade is interrupted.
