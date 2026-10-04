"""Release builds must not hide make failures behind a batch wrapper."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("release_builder", ROOT / "tools" / "build_dev_release.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)

assert builder.MAKE.is_file(), builder.MAKE
assert builder.MAKE.suffix.lower() == ".exe", builder.MAKE
try:
    builder.validate_make(ROOT / "make.CMD")
except RuntimeError as exc:
    assert "batch wrapper" in str(exc)
else:
    raise AssertionError("batch make wrapper was accepted")
print("test_release_make_selection: PASS")
