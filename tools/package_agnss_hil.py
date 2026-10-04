"""Package V3.078 AGNSS images for hardware validation after a failed RAM gate."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import zlib
from pathlib import Path

from build_dev_release import ROOT, TOOLCHAIN, build_combined, release_identity
from gen_a300_ota_image import HEADER, MAGIC, PRODUCT_ID


OUT = ROOT / "artifacts" / "A300-406-V3.078-AGNSS-HIL-20260928"
APP = ROOT / "build" / "a300_firmware.bin"
BOOT = ROOT / "bootloader" / "build" / "bootloader.bin"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    identity = release_identity()
    if identity["firmware_version_counter"] != 3078 or not identity["firmware_version"].endswith("V3.078"):
        raise ValueError("V3.078 release identity required")
    if OUT.exists():
        raise FileExistsError(f"package already exists: {OUT}")

    app, boot = APP.read_bytes(), BOOT.read_bytes()
    if not 8 <= len(app) <= 106496 or b"V3.078" not in app:
        raise ValueError("App length or embedded version is invalid")
    combined = build_combined(boot, app)
    capacity = json.loads((ROOT / "build" / "flash-capacity.json").read_text(encoding="utf-8"))
    stack = json.loads((ROOT / "build" / "stack-analysis.json").read_text(encoding="utf-8"))
    if capacity["status"] != "passed" or capacity["bin_sha256"] != hashlib.sha256(app).hexdigest():
        raise ValueError("Flash capacity evidence does not match the App")
    if stack["elf_sha256"] != sha256(ROOT / "build" / "a300_firmware.elf"):
        raise ValueError("Stack evidence does not match the App ELF")
    if stack["status"] != "incomplete":
        raise ValueError("Unexpected stack gate state; use the standard release builder")

    OUT.mkdir(parents=True, exist_ok=False)
    files = {
        "SWD-Combined-V3078.bin": combined,
        "OTA-A300-406-V3078.bin": HEADER.pack(
            MAGIC, 3078, len(app), zlib.crc32(app) & 0xFFFFFFFF, PRODUCT_ID, bytes(12)
        ) + app,
    }
    for name, data in files.items():
        (OUT / name).write_bytes(data)
    for source, name in (
        (APP, "App-V3078.bin"),
        (ROOT / "build" / "a300_firmware.hex", "App-V3078.hex"),
        (BOOT, "Bootloader-V3078.bin"),
        (ROOT / "bootloader" / "build" / "bootloader.hex", "Bootloader-V3078.hex"),
        (ROOT / "build" / "flash-capacity.json", "flash-capacity.json"),
        (ROOT / "build" / "stack-analysis.json", "stack-analysis.json"),
    ):
        shutil.copy2(source, OUT / name)

    objcopy = TOOLCHAIN / "arm-none-eabi-objcopy.exe"
    subprocess.run(
        [str(objcopy), "-I", "binary", "-O", "ihex", "--change-addresses", "0x08000000",
         str(OUT / "SWD-Combined-V3078.bin"), str(OUT / "SWD-Combined-V3078.hex")],
        check=True,
    )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    manifest = {
        "status": "HIL_ONLY_RELEASE_GATE_FAILED",
        "version": identity["firmware_version"],
        "version_code": 3078,
        "mcu": "N32L406CBL7",
        "ota_format": "a300-header-v1; platform detached signature required",
        "flash_origin": "0x08000000",
        "app_origin": "0x08006000",
        "release_gate": "RAM stack/heap/exception bound incomplete",
        "git_revision": revision,
        "git_dirty": True,
        "files": {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in sorted(OUT.iterdir()) if path.is_file()
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT / "README.txt").write_text(
        "A300-406 V3.078 AGNSS hardware-validation package.\n"
        "For an existing V3.077 device, use the OTA test flow first.\n"
        "App-V3078.hex starts at 0x08006000; direct SWD App replacement bypasses OTA rollback.\n"
        "SWD-Combined-V3078.hex contains Bootloader and App with absolute addresses.\n"
        "SWD-Combined-V3078.bin starts at 0x08000000.\n"
        "CAUTION: reflashing the Combined image reinstates the Bootloader factory-init request.\n"
        "On first boot it erases external NOR configuration, BCR, checkpoint and authorization sectors.\n"
        "Use Combined only on a blank board or an intentional factory recovery.\n"
        "Upload OTA-A300-406-V3078.bin to the FOTA test platform as A300-406, version 3078; "
        "the platform must sign and authorize it.\n"
        "HIL ONLY: the release RAM gate remains incomplete. Do not distribute as a formal release.\n",
        encoding="ascii",
    )
    print(OUT)


if __name__ == "__main__":
    main()
