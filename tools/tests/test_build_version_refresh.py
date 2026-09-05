import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "tools/build_dev_release.py").read_text(encoding="utf-8")
POWERSHELL_GENERATOR = (ROOT / "gen_version.ps1").read_text(encoding="utf-8")

assert "ZoneInfo(\"Asia/Shanghai\")" in SOURCE
assert "def refresh_build_version(" in SOURCE
refresh_call = SOURCE.index("refresh_build_version()")
app_build = SOURCE.index('run([str(MAKE),"-B","all"])')
boot_build = SOURCE.index('run([str(MAKE),"-C","bootloader","-B","all"])')
assert refresh_call < app_build < boot_build
assert 'ROOT/"include"/"build_version.h"' in SOURCE
assert "FW_FULL_VERSION" in SOURCE
assert "CultureInfo]::InvariantCulture" in POWERSHELL_GENERATOR
assert "ToString(\"MMM dd yyyy - HH:mm:ss\"" in POWERSHELL_GENERATOR

# Regression: the generator output must remain canonical for release_guard.py.
# A bare ``#endif`` changes the identity dependency digest even when only the
# timestamp is refreshed.
spec = importlib.util.spec_from_file_location(
    "build_dev_release", ROOT / "tools/build_dev_release.py"
)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as temporary:
    temporary_root = Path(temporary)
    include = temporary_root / "include"
    include.mkdir()
    header = include / "build_version.h"
    header.write_text(
        '#ifndef BUILD_VERSION_H\n#define BUILD_VERSION_H\n\n'
        '#define FW_BUILD_NUMBER  "old"\n'
        '#define FW_BUILD_DATE    "old"\n'
        '#define FW_FULL_VERSION  "T360-A300_406_20260823000000,V3.000"\n\n'
        '#endif /* BUILD_VERSION_H */\n',
        encoding="ascii",
    )
    module.ROOT = temporary_root
    module.refresh_build_version()
    generated = header.read_text(encoding="ascii")
    assert generated.endswith("#endif /* BUILD_VERSION_H */\n")

print("test_build_version_refresh: PASS")
