# Task 1 report — baseline and release guards

## Status

Implemented the Task 1 baseline manifest and release guard. Existing unrelated
working-tree edits were preserved and not staged.

## Changes

- Added `tools/release_guard.py`, scanning release-controlled paths (`src`,
  `include`, `ldscript`, `bootloader`, manifests, and packaging metadata) for
  `T663B`, `A300_202511`, and `V1.274`.
- Added `tools/tests/baseline_manifest.py`, which tests the guard with a
  temporary legacy-string fixture and records git revision plus ELF/map byte
  sizes without modifying source.
- Added `make release-guard` to `Makefile`.
- Updated `include/config.h` to the required release version
  `T360-A300_406_20260823000000,V3.000` and model `A300_406`.
- Added `docs/migration-baseline.md` documenting the pre-existing changes and
  baseline build command (`make all`).

## Verification

Commands run from `A300-first`:

```text
python tools/tests/baseline_manifest.py --self-test
baseline_manifest: PASS (release guard contract)

python tools/tests/baseline_manifest.py
baseline_manifest: PASS (release guard contract)
git_revision: 997293904926c685e7a569f4dd7185bccbff317a
ELF bytes: 1019328
MAP bytes: 767438
```

`git diff --check` passed.

`python tools/release_guard.py` ran and correctly failed closed on three
remaining legacy identifiers in pre-existing files:

```text
src/jt808_params.c:212  T663B01
src/main.c:226          T663B01
include/build_version.h:7 T663B_B409_20260608_193540
release-guard: FAIL (3 match(es))
```

The `make release-guard` command could not be executed because GNU Make is not
installed in this environment (`make` is not recognized by PowerShell). The
Python guard entry point used by the target was executed directly.

## Risks / concerns

- The repository guard remains red until the later version-unification task
  updates `include/build_version.h` and the two terminal-ID literals. Those
  files are outside Task 1's permitted modifications (and the build-version
  file already contains user changes), so they were intentionally left alone.
- Existing build artifacts are large byte sizes and are measurements of files
  currently present in `build`; no clean rebuild was possible without GNU Make.
