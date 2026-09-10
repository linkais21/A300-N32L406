# Versioned Release Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate each A300 firmware release in an immutable `artifacts/V<major>.<revision>` directory containing App, Bootloader, complete programming, OTA, diagnostic, and checksum files.

**Architecture:** Keep `release_identity.json` as the sole version source and add small, independently testable path helpers to `tools/build_dev_release.py`. Reserve the version directory before compilation so an existing release is rejected before any generated source or build output changes, then place every copied or generated artifact directly in that reserved directory.

**Tech Stack:** Python 3, `pathlib`, `argparse`, ARM GNU Toolchain, Make, existing standalone Python contract tests.

## Global Constraints

- The default artifacts root is exactly `A300-first/artifacts`.
- The current version directory is exactly `artifacts/V3.002`, derived from the trailing version token in `release_identity.json`.
- An existing version directory is immutable: never delete, clear, merge into, or overwrite it.
- The directory contains App, Bootloader, Combined, OTA, ELF, HEX, MAP, and SHA-256 manifest artifacts.
- `--output` denotes an alternate artifacts root; the derived version directory is still appended.
- Do not commit, push, flash hardware, overwrite `firmware/`, or deploy services.
- Preserve all unrelated working-tree changes.

---

### Task 1: Define And Test The Version Directory Contract

**Files:**
- Modify: `tools/tests/test_dev_release_manifest.py`
- Modify: `tools/build_dev_release.py`

**Interfaces:**
- Consumes: `release_identity.json` field `firmware_version`, currently `T360-A300_406_20260823000000,V3.002`.
- Produces: `release_version_label(identity: dict) -> str`, returning `V3.002` for the current identity and raising `ValueError` for a missing or malformed trailing token.
- Produces: `release_output_dir(output_root: Path, identity: dict) -> Path`, returning `output_root / release_version_label(identity)`.

- [x] **Step 1: Add failing helper contract tests**

Extend the test's imported-module section with assertions equivalent to:

```python
assert module.release_version_label(identity) == "V3.002"
assert module.release_output_dir(Path("artifacts"), identity) == Path("artifacts/V3.002")

for malformed in (
    {},
    {"firmware_version": "V3.002-extra"},
    {"firmware_version": "T360-A300_406_20260823000000,3.002"},
):
    try:
        module.release_version_label(malformed)
    except ValueError as exc:
        assert "firmware_version" in str(exc)
    else:
        raise AssertionError(f"malformed version accepted: {malformed!r}")
```

- [x] **Step 2: Run the focused test and confirm RED**

Run: `python tools/tests/test_dev_release_manifest.py`

Expected: FAIL because `release_version_label` does not exist and the current builder uses a UTC timestamp directory.

- [x] **Step 3: Implement strict version parsing and path derivation**

Add focused helpers using a full trailing-token match:

```python
VERSION_LABEL_RE = re.compile(r"(?:^|,)V[0-9]+\.[0-9]{3}$")

def release_version_label(identity: dict) -> str:
    version = identity.get("firmware_version")
    if not isinstance(version, str):
        raise ValueError("release_identity.json firmware_version must end in V<major>.<revision>")
    match = VERSION_LABEL_RE.search(version)
    if match is None:
        raise ValueError("release_identity.json firmware_version must end in V<major>.<revision>")
    return match.group(0).lstrip(",")

def release_output_dir(output_root: Path, identity: dict) -> Path:
    return output_root / release_version_label(identity)
```

The parser must accept the repository's current identity and reject suffixes or absent `V` prefixes.

- [x] **Step 4: Run the focused test and confirm GREEN**

Run: `python tools/tests/test_dev_release_manifest.py`

Expected: PASS.

---

### Task 2: Reserve An Immutable Version Directory Before Building

**Files:**
- Modify: `tools/tests/test_dev_release_manifest.py`
- Modify: `tools/build_dev_release.py`

**Interfaces:**
- Consumes: `release_output_dir(output_root, identity)` from Task 1.
- Produces: `reserve_release_dir(output_root: Path, identity: dict) -> Path`, which creates the version directory with `parents=True, exist_ok=False` and returns it.
- Changes CLI: `--output` defaults to `ROOT / "artifacts"`; the value is the root, not the final version directory.

- [x] **Step 1: Add failing immutability tests**

In a temporary directory, call `reserve_release_dir` once, create a sentinel inside it, call it again, and assert the second call raises `FileExistsError` while the sentinel bytes are unchanged:

```python
output_root = temporary_root / "artifacts"
release_dir = module.reserve_release_dir(output_root, identity)
assert release_dir == output_root / "V3.002"
sentinel = release_dir / "existing.bin"
sentinel.write_bytes(b"do-not-overwrite")
try:
    module.reserve_release_dir(output_root, identity)
except FileExistsError:
    pass
else:
    raise AssertionError("existing version directory was accepted")
assert sentinel.read_bytes() == b"do-not-overwrite"
```

Also inspect the script text to assert the CLI default contains `ROOT/"artifacts"` and no longer constructs `build_id` or appends a UTC timestamp.

- [x] **Step 2: Run the focused test and confirm RED**

Run: `python tools/tests/test_dev_release_manifest.py`

Expected: FAIL because `reserve_release_dir` is absent and the default is still `dist/dev-key`.

- [x] **Step 3: Implement early reservation and remove timestamp output**

Implement:

```python
def reserve_release_dir(output_root: Path, identity: dict) -> Path:
    path = release_output_dir(output_root.resolve(), identity)
    path.mkdir(parents=True, exist_ok=False)
    return path
```

Change the default to `ROOT/"artifacts"`. In `main`, call `reserve_release_dir(args.output, identity)` after validating tools and before `refresh_build_version()` or any Make invocation. Remove `build_id` and timestamp-based path construction. On collision, allow the command to exit nonzero with a message identifying the existing version path; do not catch the error to delete or reuse the directory.

- [x] **Step 4: Run the focused test and confirm GREEN**

Run: `python tools/tests/test_dev_release_manifest.py`

Expected: PASS and the sentinel remains unchanged.

---

### Task 3: Verify Required Artifacts And Document Operator Usage

**Files:**
- Modify: `tools/tests/test_dev_release_manifest.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: the manifest schema and filenames already emitted by `tools/build_dev_release.py`.
- Produces: documented command `python tools/build_dev_release.py` and immutable output contract `artifacts/V3.002/`.

- [x] **Step 1: Strengthen manifest location and contents validation**

Update `validate(path)` so it additionally derives the expected version label from `release_identity.json`, asserts `path.parent.name == expected_label`, and asserts the exact required artifact keys remain present:

```python
expected_label = "V" + identity["firmware_version"].rsplit("V", 1)[1]
assert path.parent.name == expected_label
required = {
    "app_bin", "app_elf", "app_hex", "app_map",
    "bootloader_bin", "bootloader_elf", "bootloader_hex", "bootloader_map",
    "combined_bin", "ota_upload_bin",
}
assert required <= data["artifacts"].keys()
```

Keep the existing byte-size and SHA-256 checks for every manifest entry.

- [x] **Step 2: Update the README release section**

Document that `python tools/build_dev_release.py` creates `artifacts/<version>/`, that `V3.002` is read from `release_identity.json`, list the primary files and their purposes, and state that an existing version directory causes a hard failure. Document `--output D:\some\root` as changing only the root, producing `D:\some\root\V3.002`.

- [x] **Step 3: Run focused non-build tests**

Run:

```powershell
python tools/tests/test_dev_release_manifest.py
python tools/tests/test_a300_ota_image.py
python tools/tests/test_bootloader_artifacts.py
python tools/tests/test_release_identity_contract.py
```

Expected: all four commands print `PASS` and return zero.

- [x] **Step 4: Generate the current immutable release**

First verify `artifacts/V3.002` does not exist. Then run:

```powershell
python tools/build_dev_release.py
```

Expected: App and Bootloader compile without warnings; RAM guards pass; `artifacts/V3.002/SHA256SUMS-N32L406CBL7.json` is printed. If the directory already exists, stop and report it; never remove or overwrite it.

- [x] **Step 5: Validate the generated manifest and collision behavior**

Run:

```powershell
python tools/tests/test_dev_release_manifest.py --manifest artifacts/V3.002/SHA256SUMS-N32L406CBL7.json
python tools/build_dev_release.py
```

Expected: manifest validation prints `PASS`; the second build fails before compilation because `artifacts/V3.002` exists and all hashes in the existing manifest remain unchanged.

- [x] **Step 6: Run release gates and inspect scope**

Run:

```powershell
make release-guard
make ram-guard
make stack-guard
git diff --check
git diff -- tools/build_dev_release.py tools/tests/test_dev_release_manifest.py README.md docs/superpowers/specs/2026-09-10-versioned-release-artifacts-design.md docs/superpowers/plans/2026-09-10-versioned-release-artifacts.md
git status --short
```

Expected: guards and `git diff --check` return zero; scoped diff contains no secret, debug-only behavior, deletion, deployment, or flashing changes. Report the pre-existing unrelated dirty files separately. Hardware programming and OTA installation remain unexecuted and need real-device/HIL verification.
