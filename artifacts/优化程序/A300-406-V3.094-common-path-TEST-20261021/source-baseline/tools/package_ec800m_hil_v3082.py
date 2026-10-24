"""Package the EC800M startup probe fix for one dedicated HIL device."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from build_dev_release import (
    ROOT,
    build_combined,
    release_identity,
    validate_app_vectors,
    validate_factory_init_marker,
)


VERSION = 3082
LABEL = "N32L406CBL7"
OUT = ROOT / "artifacts" / "A300-406-V3.082-EC800M-RX-PROBE-HIL-20261002"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    identity = release_identity()
    if identity["firmware_version_counter"] != VERSION or not identity["firmware_version"].endswith("V3.082"):
        raise RuntimeError("release_identity.json is not V3.082")
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite {OUT}")

    app_source = ROOT / "build" / "a300_firmware.bin"
    boot_source = ROOT / "bootloader" / "build" / "bootloader.bin"
    app = app_source.read_bytes()
    boot = boot_source.read_bytes()
    validate_app_vectors(app)
    validate_factory_init_marker(boot)
    if len(app) > 106496 or len(boot) > 0x6000:
        raise RuntimeError("image exceeds frozen flash layout")
    combined = build_combined(boot, app)

    OUT.mkdir(parents=True, exist_ok=False)
    files: dict[str, Path] = {}
    sources = {
        f"App-{LABEL}.bin": app_source,
        f"App-{LABEL}.elf": ROOT / "build" / "a300_firmware.elf",
        f"App-{LABEL}.hex": ROOT / "build" / "a300_firmware.hex",
        f"App-{LABEL}.map": ROOT / "build" / "a300_firmware.map",
        f"Bootloader-{LABEL}.bin": boot_source,
        f"Bootloader-{LABEL}.elf": ROOT / "bootloader" / "build" / "bootloader.elf",
        f"Bootloader-{LABEL}.hex": ROOT / "bootloader" / "build" / "bootloader.hex",
        f"Bootloader-{LABEL}.map": ROOT / "bootloader" / "build" / "bootloader.map",
        "flash-capacity.json": ROOT / "build" / "flash-capacity.json",
    }
    for name, source in sources.items():
        target = OUT / name
        shutil.copy2(source, target)
        files[name] = target

    combined_target = OUT / f"Combined-{LABEL}.bin"
    combined_target.write_bytes(combined)
    files[combined_target.name] = combined_target

    ota_target = OUT / f"A300-406-OTA-V{VERSION}.bin"
    subprocess.run(
        [sys.executable, "tools/gen_a300_ota_image.py", "--input", str(files[f"App-{LABEL}.bin"]),
         "--output", str(ota_target), "--version-code", str(VERSION)],
        cwd=ROOT,
        check=True,
    )
    files[ota_target.name] = ota_target

    manifest = {
        "purpose": "DEDICATED_DEVICE_HIL_ONLY",
        "release_approved": False,
        "version": identity["firmware_version"],
        "version_code": VERSION,
        "product": "A300-406",
        "mcu": LABEL,
        "memory": {"boot_origin": "0x08000000", "app_origin": "0x08006000", "app_limit_bytes": 106496},
        "fix_scope": "EC800M startup power-probe response path; trajectory/GPS/AGNSS code unchanged",
        "release_gate": "blocked: stack evidence incomplete and RAM guard reports changed IRQ policy in src/hw_init.c",
        "files": {name: {"bytes": path.stat().st_size, "sha256": sha256(path)} for name, path in sorted(files.items())},
    }
    manifest_path = OUT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "SHA256SUMS.txt").write_text(
        "".join(f"{entry['sha256']}  {name}\n" for name, entry in manifest["files"].items()),
        encoding="ascii",
    )
    (OUT / "README.txt").write_text(
        "V3.082 EC800M startup probe fix, dedicated-device HIL package only.\n"
        "This package is not release approved because the repository release gate is blocked by\n"
        "incomplete whole-program stack evidence and the existing hw_init.c IRQ-policy RAM guard.\n"
        "Use Combined-N32L406CBL7.bin at 0x08000000 for a full SWD/production-tool image, or\n"
        "App-N32L406CBL7.bin at 0x08006000 only when the existing bootloader is retained.\n"
        "Do not use the previous V3.082 Trajectory-Fix package or the V3.081 DMA retest packages.\n"
        "Validate cold boot, SIM/IMEI/ICCID, REG=1, PDP, JT808 online, and repeated HEALTH logs.\n"
        "No physical device has been flashed or validated by this build step.\n",
        encoding="ascii",
    )
    print(OUT)
    print(f"Combined SHA-256: {sha256(combined_target)}")
    print(f"App SHA-256: {sha256(files[f'App-{LABEL}.bin'])}")
    print(f"OTA SHA-256: {sha256(ota_target)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
