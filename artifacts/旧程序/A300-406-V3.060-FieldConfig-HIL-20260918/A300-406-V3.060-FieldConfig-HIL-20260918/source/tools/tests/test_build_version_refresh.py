import importlib.util
import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "tools/build_dev_release.py").read_text(encoding="utf-8")
POWERSHELL_GENERATOR = (ROOT / "gen_version.ps1").read_text(encoding="utf-8")

assert "ZoneInfo(\"Asia/Shanghai\")" in SOURCE
assert "def refresh_build_version(" in SOURCE
refresh_call = SOURCE.index("refresh_build_version()")
app_build = SOURCE.index('run([str(MAKE),"-B","all"')
boot_build = SOURCE.index('run([str(MAKE),"-C","bootloader","-B","all"')
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
    (temporary_root / "release_identity.json").write_text(
        '{"firmware_version":"T360-A300_406_20260823000000,V3.001",'
        '"firmware_version_counter":3001}\n',
        encoding="utf-8",
    )
    header = include / "build_version.h"
    header.write_text(
        '#ifndef BUILD_VERSION_H\n#define BUILD_VERSION_H\n\n'
        '#define FW_BUILD_NUMBER  "old"\n'
        '#define FW_BUILD_DATE    "old"\n'
        '#define FW_FULL_VERSION  "T360-A300_406_20260823000000,V3.000"\n\n'
        '#endif /* BUILD_VERSION_H */\n',
        encoding="ascii",
    )
    config = include / "config.h"
    config.write_text('#define FW_VERSION_STR "T360-A300_406_20260823000000,V3.000"\n', encoding="utf-8")
    module.ROOT = temporary_root
    module.refresh_build_version()
    generated = header.read_text(encoding="ascii")
    assert re.search(r'FW_BUILD_NUMBER\s+"\d{12}"', generated), 'compile stamp must be YYYYMMDDHHMM'
    stamp = re.search(r'FW_FULL_VERSION\s+"T360-A300_406_(\d{14}),V3.001"', generated).group(1)
    assert stamp != '20260823000000', 'full version must use creation time'
    assert stamp[:12] in generated
    assert f'T360-A300_406_{stamp},V3.001' in config.read_text()
    saved = json.loads((temporary_root / 'release_identity.json').read_text())
    assert saved['firmware_version'] == f'T360-A300_406_{stamp},V3.001'
    assert '#define FW_VERSION_COUNTER  3001UL' in generated
    assert generated.endswith("#endif /* BUILD_VERSION_H */\n")

    for invalid_counter in (0, 0x1_0000_0000, True, False):
        (temporary_root / "release_identity.json").write_text(
            json.dumps({
                "firmware_version": "T360-A300_406_20260823000000,V3.001",
                "firmware_version_counter": invalid_counter,
            }) + "\n",
            encoding="utf-8",
        )
        try:
            module.refresh_build_version()
        except ValueError as exc:
            assert "firmware_version_counter" in str(exc)
        else:
            raise AssertionError(f"invalid counter {invalid_counter} was accepted")

    powershell_generator = temporary_root / "gen_version.ps1"
    powershell_generator.write_text(POWERSHELL_GENERATOR, encoding="utf-8")
    (temporary_root / "release_identity.json").write_text(
        json.dumps({
            "firmware_version": "T360-A300_406_20260823000000,V3.001",
            "firmware_version_counter": 3001,
        }) + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(powershell_generator)],
        cwd=temporary_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    generated = header.read_text(encoding="ascii")
    assert '#define FW_VERSION_COUNTER  3001UL' in generated
    stamp = re.search(r'FW_FULL_VERSION\s+"T360-A300_406_(\d{14}),V3.001"', generated).group(1)
    assert stamp != '20260823000000'
    assert f'T360-A300_406_{stamp},V3.001' in config.read_text()
    saved = json.loads((temporary_root / 'release_identity.json').read_text())
    assert saved['firmware_version'] == f'T360-A300_406_{stamp},V3.001'

    for invalid_counter in (True, False):
        (temporary_root / "release_identity.json").write_text(
            json.dumps({
                "firmware_version": "T360-A300_406_20260823000000,V3.001",
                "firmware_version_counter": invalid_counter,
            }) + "\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(powershell_generator)],
            cwd=temporary_root,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "firmware_version_counter" in result.stdout + result.stderr

print("test_build_version_refresh: PASS")
