# Versioned Release Artifacts Design

## Goal

Every generated A300 firmware release is stored in a directory named after
the firmware version under `A300-first/artifacts`. For the current release,
the output directory is `artifacts/V3.002`.

## Version Source

`release_identity.json` remains the only version source. The release builder
derives the directory name from the trailing `V<major>.<revision>` component
of `firmware_version`. It rejects a missing or malformed version component.

## Output Contract

The release builder creates exactly one directory per version:

```text
artifacts/
  V3.002/
    App-N32L406CBL7.bin
    App-N32L406CBL7.elf
    App-N32L406CBL7.hex
    App-N32L406CBL7.map
    Bootloader-N32L406CBL7.bin
    Bootloader-N32L406CBL7.elf
    Bootloader-N32L406CBL7.hex
    Bootloader-N32L406CBL7.map
    Combined-N32L406CBL7.bin
    A300-406-OTA-V3002.bin
    SHA256SUMS-N32L406CBL7.json
```

The App and Bootloader files support separate programming and diagnostics.
The Combined image is the normal complete programming image. The OTA image is
the platform upload package. The JSON manifest records sizes and SHA-256 hashes
for all generated artifacts.

## Immutability And Failures

The builder must refuse to continue if `artifacts/V3.002` already exists. It
must never delete, clear, merge into, or overwrite an existing version
directory. Build, size, vector, package, or manifest failures return a nonzero
exit status and must not replace a previous release.

The optional `--output` argument, if retained, identifies the artifacts root;
the version directory is always appended by the builder. Its default is
`A300-first/artifacts`.

## Tests And Documentation

Tests must first demonstrate failure with the timestamp-based implementation,
then verify:

- `V3.002` is derived from the release identity.
- the default release path is `artifacts/V3.002`;
- every required App, Bootloader, Combined, OTA, and manifest artifact is in
  that directory;
- an existing version directory is rejected without modification;
- a malformed firmware version is rejected.

The firmware README will document the output path, contents, immutability rule,
and release command. Verification will include the focused release tests,
release build and guards where the local toolchain permits, `git diff --check`,
and scoped diff inspection. Flashing and OTA installation remain unperformed
and require hardware/HIL verification.
