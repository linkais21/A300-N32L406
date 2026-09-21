import json
import re
import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT.parent
CONTRACT_PATH = ROOT / "release_identity.json"

contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

assert contract == {
    "firmware_version_prefix": "T360-A300_406_20260823000000,V3.",
    "firmware_revision": 50,
    "firmware_version": "T360-A300_406_20260823000000,V3.050",
    "firmware_version_counter": 3050,
    "ota_device_model": "A300-406",
    "jt808_terminal_model": "T360-A300",
    "jt808_manufacturer_id": "70110",
}
assert contract["firmware_version"] == (
    contract["firmware_version_prefix"]
    + f'{contract["firmware_revision"]:03d}'
)
assert 0 < contract["firmware_version_counter"] <= 0xFFFFFFFF

config = (ROOT / "include/config.h").read_text(encoding="utf-8-sig")
expected_macros = {
    "FW_VERSION_STR": contract["firmware_version"],
    "FW_OTA_MODEL_STR": contract["ota_device_model"],
    "FW_JT808_MODEL_STR": contract["jt808_terminal_model"],
    "FW_MANUFACTURER_ID_STR": contract["jt808_manufacturer_id"],
}
for name, value in expected_macros.items():
    assert re.search(rf'#define\s+{name}\s+"{re.escape(value)}"', config), name

main_source = (ROOT / "src/main.c").read_text(encoding="utf-8-sig")
assert "FW_MANUFACTURER_ID_STR" in main_source
assert "FW_JT808_MODEL_STR" in main_source
flash_config = (ROOT / "src/flash_config.c").read_text(encoding="utf-8-sig")
assert '.terminal_model     = "T360-A300"' in flash_config

generator = (ROOT / "gen_version.ps1").read_text(encoding="utf-8-sig")
assert "release_identity.json" in generator
assert "ConvertFrom-Json" in generator
assert '$IDENTITY.firmware_version' in generator

release_guard = (ROOT / "tools/release_guard.py").read_text(encoding="utf-8-sig")
assert "release_identity.json" in release_guard
assert 'CONTRACT["firmware_version"]' in release_guard
assert 'CONTRACT["firmware_version_counter"]' in release_guard

spec = importlib.util.spec_from_file_location("release_guard", ROOT / "tools/release_guard.py")
guard = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(guard)
assert guard.CANONICAL_IDENTITY_FILE_SHA256["include/build_version.h"] == guard.canonical_file_digest(
    (ROOT / "include/build_version.h").read_text(encoding="utf-8-sig"),
    "include/build_version.h",
)
with tempfile.TemporaryDirectory() as temporary:
    temporary_root = Path(temporary)
    include = temporary_root / "include"
    include.mkdir()
    (temporary_root / "release_identity.json").write_text(
        json.dumps(contract) + "\n",
        encoding="utf-8",
    )
    header = (ROOT / "include/build_version.h").read_text(encoding="utf-8-sig")
    (include / "build_version.h").write_text(
        header.replace(f"#define FW_VERSION_COUNTER  {contract['firmware_version_counter']}UL",
                       f"#define FW_VERSION_COUNTER  {contract['firmware_version_counter'] + 1}UL"),
        encoding="ascii",
    )
    findings = guard.scan(temporary_root, ("release_identity.json", "include/build_version.h"))
    assert any(token == "<version-counter>" for _, _, token, _ in findings)

    for invalid_counter in (0, 0x1_0000_0000, True, False):
        invalid_contract = {**contract, "firmware_version_counter": invalid_counter}
        guard.CONTRACT = invalid_contract
        (temporary_root / "release_identity.json").write_text(
            json.dumps(invalid_contract) + "\n",
            encoding="utf-8",
        )
        findings = guard.scan(temporary_root, ("release_identity.json",))
        assert any(token == "<version-counter>" for _, _, token, _ in findings)

for path in (
    WORKSPACE / "fota-platform/backend/src/main/resources/application.yml",
    WORKSPACE / "fota-platform/backend/src/main/resources/application-prod.yml",
):
    text = path.read_text(encoding="utf-8-sig")
    assert re.search(r"default-device-model:\s+(?:\$\{[^}:]+:)?A300-406\}?", text)

print("test_release_identity_contract: PASS")
