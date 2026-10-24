"""Check the generated SWD baseline and OTA test package as delivery artifacts."""

import hashlib
import json
from pathlib import Path
import struct
import zipfile
import zlib


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "A300-406-V3.076-V3.077-Stability-HIL-20260926"
HEADER = struct.Struct("<IIIII12s")
MARKER = struct.Struct("<IHHIIIII")


def test_delivery_pair():
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="ascii"))
    assert manifest["purpose"] == "HIL_TEST_ONLY"
    assert (manifest["baseline_version_code"], manifest["upgrade_version_code"]) == (3076, 3077)
    assert manifest["upgrade_app_flash_remaining"] >= 1800
    assert manifest["release_gate"].startswith("FAILED:")

    for name, entry in manifest["files"].items():
        data = (OUT / name).read_bytes()
        assert len(data) == entry["bytes"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]

    base = (OUT / "SWD-Combined-V3076.bin").read_bytes()
    recovery = (OUT / "SWD-Recovery-Combined-V3077.bin").read_bytes()
    base_app, upgrade_app = base[0x6000:], recovery[0x6000:]
    source = manifest["source_binaries"]
    assert hashlib.sha256(base[:22556]).hexdigest() == source["baseline_boot_sha256"]
    assert hashlib.sha256(recovery[:22556]).hexdigest() == source["upgrade_boot_sha256"]
    assert hashlib.sha256(base_app).hexdigest() == source["baseline_app_sha256"]
    assert hashlib.sha256(upgrade_app).hexdigest() == source["upgrade_app_sha256"]
    assert b"V3.076" in base_app and b"V3.077" in upgrade_app
    assert MARKER.unpack_from(base, 0x5800) == (
        0x494E4946, 1, MARKER.size, 1, 0x0F, 0xAF19BCAA, 0x52455144, 0xFFFFFFFF
    )
    assert MARKER.unpack_from(recovery, 0x5800) == MARKER.unpack_from(base, 0x5800)
    msp, reset = struct.unpack_from("<II", base, 0x6000)
    assert 0x20000000 <= msp <= 0x20006000 and msp % 8 == 0
    assert 0x08006001 <= reset < 0x08020000 and reset & 1

    ota = (OUT / "OTA-A300-406-V3077.bin").read_bytes()
    magic, version, size, crc, product, reserved = HEADER.unpack_from(ota)
    assert (magic, version, size, product, reserved) == (
        0xA300B007, 3077, len(upgrade_app), 0x41333030, bytes(12)
    )
    assert crc == zlib.crc32(upgrade_app) & 0xFFFFFFFF
    assert ota[HEADER.size:] == upgrade_app

    with zipfile.ZipFile(OUT.parent / f"{OUT.name}.zip") as bundle:
        assert bundle.testzip() is None
        assert set(bundle.namelist()) == {path.name for path in OUT.iterdir()}
        for name in bundle.namelist():
            assert bundle.read(name) == (OUT / name).read_bytes()


if __name__ == "__main__":
    test_delivery_pair()
    print("test_stability_hil_pair: PASS")
