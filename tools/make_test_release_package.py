from pathlib import Path
import hashlib
import json
import struct
import sys
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_dev_release import (
    build_combined,
    validate_app_vectors,
    validate_factory_init_marker,
)

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build-release-final"
OUT = ROOT / "artifacts" / "A300-406-V3.073-Optimization-20260923"
VERSION = "T360-A300_406_20260923000659,V3.073"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=False)
    app = (BUILD / "a300_firmware.bin").read_bytes()
    boot_build = ROOT / "bootloader" / "build"
    boot = (boot_build / "bootloader.bin").read_bytes()
    validate_factory_init_marker(boot)
    validate_app_vectors(app)
    combined = build_combined(boot, app)
    files = {
        "App-N32L406-V3.073.bin": app,
        "App-N32L406-V3.073.hex": (BUILD / "a300_firmware.hex").read_bytes(),
        "Bootloader-N32L406-V3.073.bin": boot,
        "Bootloader-N32L406-V3.073.hex": (boot_build / "bootloader.hex").read_bytes(),
        "Combined-N32L406-V3.073.bin": combined,
    }
    header = struct.pack(
        "<IIIII12s", 0xA300B007, 3073, len(app), zlib.crc32(app) & 0xFFFFFFFF,
        0x41333030, bytes(12)
    )
    files["A300-406-OTA-V3073.bin"] = header + app
    for name, content in files.items():
        (OUT / name).write_bytes(content)
    manifest = {
        "version": VERSION,
        "version_code": 3073,
        "app_size": len(app),
        "app_flash_origin": "0x08006000",
        "app_flash_limit": 106496,
        "app_flash_remaining": 106496 - len(app),
        "ota_format": "a300-header-v1",
        "hardware": "N32L406CBL7",
        "artifacts": {
            name: {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            for name, content in files.items()
        },
    }
    (OUT / "release-test-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "SHA256SUMS.txt").write_text(
        "".join(f'{v["sha256"]}  {k}\n' for k, v in manifest["artifacts"].items()),
        encoding="ascii",
    )
    archive = OUT.parent / f"{OUT.name}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in files:
            bundle.write(OUT / name, name)
        bundle.write(OUT / "release-test-manifest.json", "release-test-manifest.json")
        bundle.write(OUT / "SHA256SUMS.txt", "SHA256SUMS.txt")
    print(OUT)
    print(archive)


if __name__ == "__main__":
    main()
