#!/usr/bin/env python3
"""Package the reviewed V3.076 -> V3.077 SWD/OTA HIL test pair."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_dev_release import build_combined, validate_app_vectors
from tools.gen_a300_ota_image import HEADER, MAGIC, PRODUCT_ID


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "build-hil-v3076"
UPGRADE = ROOT / "build-hil-v3077"
OUT = ROOT / "artifacts" / "A300-406-V3.076-V3.077-Stability-HIL-20260926"
OBJCOPY = ROOT / ".toolchain" / "bin" / "arm-none-eabi-objcopy.exe"
APP_LIMIT = 106496


def image(build: Path, version: int, boot: Path) -> tuple[bytes, bytes]:
    identity = json.loads((build / "release_identity.json").read_text(encoding="utf-8"))
    if identity["firmware_version_counter"] != version or not identity["firmware_version"].endswith(f"V3.{version - 3000:03d}"):
        raise ValueError(f"version identity mismatch: {build}")
    app = (build / "a300_firmware.bin").read_bytes()
    if len(app) > APP_LIMIT or f"V3.{version - 3000:03d}".encode() not in app:
        raise ValueError(f"App identity or size mismatch: {build}")
    validate_app_vectors(app)
    boot_bytes = boot.read_bytes()
    build_combined(boot_bytes, app)
    return boot_bytes, app


def make_hex(binary: Path, output: Path) -> None:
    subprocess.run([str(OBJCOPY), "-I", "binary", "-O", "ihex",
                    "--change-addresses=0x08000000", str(binary), str(output)],
                   check=True, capture_output=True, text=True)
    roundtrip = output.with_suffix(".roundtrip.bin")
    try:
        subprocess.run([str(OBJCOPY), "-I", "ihex", "-O", "binary",
                        str(output), str(roundtrip)],
                       check=True, capture_output=True, text=True)
        if roundtrip.read_bytes() != binary.read_bytes():
            raise ValueError(f"HEX roundtrip mismatch: {output}")
    finally:
        roundtrip.unlink(missing_ok=True)


def main() -> None:
    archive = OUT.parent / f"{OUT.name}.zip"
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite {OUT}")
    if archive.exists():
        raise FileExistsError(f"refusing to overwrite {archive}")
    if not OBJCOPY.is_file():
        raise FileNotFoundError(OBJCOPY)
    base_boot, base_app = image(BASE, 3076, BASE / "bootloader.bin")
    upgrade_boot, upgrade_app = image(UPGRADE, 3077, ROOT / "bootloader" / "build" / "bootloader.bin")
    if base_app == upgrade_app:
        raise ValueError("OTA App must have a newer embedded version")

    package = HEADER.pack(MAGIC, 3077, len(upgrade_app),
                          zlib.crc32(upgrade_app) & 0xFFFFFFFF,
                          PRODUCT_ID, bytes(12)) + upgrade_app
    if HEADER.unpack_from(package)[:3] != (MAGIC, 3077, len(upgrade_app)) or package[HEADER.size:] != upgrade_app:
        raise ValueError("OTA transport header validation failed")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".stability-hil-", dir=OUT.parent) as temporary:
        stage = Path(temporary) / "package"
        stage.mkdir()
        files = {
            "SWD-Combined-V3076.bin": build_combined(base_boot, base_app),
            "SWD-Recovery-Combined-V3077.bin": build_combined(upgrade_boot, upgrade_app),
            "OTA-A300-406-V3077.bin": package,
        }
        for name, content in files.items():
            (stage / name).write_bytes(content)
        for version, name in ((3076, "SWD-Combined-V3076"),
                              (3077, "SWD-Recovery-Combined-V3077")):
            make_hex(stage / f"{name}.bin", stage / f"{name}.hex")

        manifest = {
            "purpose": "HIL_TEST_ONLY",
            "hardware": "N32L406CBL7",
            "product": "A300-406",
            "baseline_version_code": 3076,
            "upgrade_version_code": 3077,
            "app_flash_limit": APP_LIMIT,
            "baseline_app_bytes": len(base_app),
            "upgrade_app_bytes": len(upgrade_app),
            "upgrade_app_flash_remaining": APP_LIMIT - len(upgrade_app),
            "ota_signing": "platform-detached; upload transport image for platform signing",
            "release_gate": "FAILED: whole-program RAM/stack evidence incomplete",
            "source_binaries": {
                "baseline_app_sha256": hashlib.sha256(base_app).hexdigest(),
                "baseline_boot_sha256": hashlib.sha256(base_boot).hexdigest(),
                "upgrade_app_sha256": hashlib.sha256(upgrade_app).hexdigest(),
                "upgrade_boot_sha256": hashlib.sha256(upgrade_boot).hexdigest(),
            },
            "files": {},
        }
        readme = (
            "A300-406 V3.076 -> V3.077 stability HIL test pair\n\n"
            "1. Program SWD-Combined-V3076.hex, or the matching BIN at 0x08000000.\n"
            "   Verify first boot and the one-time external NOR factory initialization.\n"
            "2. Upload OTA-A300-406-V3077.bin to the FOTA test platform as model\n"
            "   A300-406, version code 3077. The platform must sign and authorize it.\n"
            "3. Upgrade a V3.076 test device and verify trial, ACTIVE, LKG and\n"
            "   token-bound SUCCESS. Do not upload a Combined image as an OTA body.\n"
            "4. SWD-Recovery-Combined-V3077 is a recovery image, not the OTA test\n"
            "   baseline. Its HEX carries addresses; its BIN starts at 0x08000000.\n\n"
            "HIL TEST ONLY: release-gate fails on incomplete RAM/stack proof.\n"
            "Real power-cut, weak-network and rollback tests are still required.\n"
        )
        (stage / "README.txt").write_text(readme, encoding="ascii")
        for path in sorted(stage.iterdir()):
            manifest["files"][path.name] = {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
        (stage / "SHA256SUMS.txt").write_text(
            "".join(f"{entry['sha256']}  {name}\n" for name, entry in manifest["files"].items()),
            encoding="ascii",
        )
        stage.rename(OUT)

    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(OUT.iterdir()):
            bundle.write(path, path.name)
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
    print(OUT)
    print(archive)


if __name__ == "__main__":
    main()
