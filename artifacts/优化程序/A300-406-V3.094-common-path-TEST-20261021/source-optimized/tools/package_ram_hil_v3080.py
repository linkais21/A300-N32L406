"""Package the gated V3.080 App for dedicated-device HIL only."""

from __future__ import annotations

import hashlib
import json
import shutil
import zlib
from pathlib import Path

from build_dev_release import ROOT, release_identity, validate_app_vectors
from gen_a300_ota_image import HEADER, MAGIC, PRODUCT_ID


BUILD = ROOT / "build-ram-hil-v3080"
OUT = ROOT / "artifacts" / "A300-406-V3.080-RAM-HIL-TEST-ONLY-20260928"
VERSION = 3080


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    identity = release_identity()
    if (identity["firmware_version_counter"] != VERSION or
            not identity["firmware_version"].endswith("V3.080")):
        raise ValueError("V3.080 release identity required")
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite {OUT}")

    elf = BUILD / "a300_firmware.elf"
    image = BUILD / "a300_firmware.bin"
    map_file = BUILD / "a300_firmware.map"
    budget_file = BUILD / "ram-budget.json"
    budget = json.loads(budget_file.read_text(encoding="utf-8"))
    capacity = json.loads((BUILD / "flash-capacity.json").read_text(encoding="utf-8"))
    app = image.read_bytes()
    validate_app_vectors(app)
    if (budget["status"] != "pass" or budget["runtime_gap"] < 4096 or
            budget["elf_sha256"] != digest(elf) or
            budget["map_sha256"] != digest(map_file) or
            capacity["status"] != "passed" or
            capacity["bin_sha256"] != hashlib.sha256(app).hexdigest() or
            b"V3.080" not in app or len(app) > 106496):
        raise ValueError("final image or release-gate evidence mismatch")

    ota = HEADER.pack(MAGIC, VERSION, len(app), zlib.crc32(app) & 0xFFFFFFFF,
                      PRODUCT_ID, bytes(12)) + app
    if HEADER.unpack_from(ota)[:3] != (MAGIC, VERSION, len(app)):
        raise ValueError("OTA header mismatch")
    OUT.mkdir(parents=True, exist_ok=False)
    app_target = OUT / "App-N32L406-V3.080-HIL.bin"
    ota_target = OUT / "OTA-A300-406-V3080-HIL.bin"
    app_target.write_bytes(app)
    ota_target.write_bytes(ota)
    for source in (elf, map_file, budget_file, BUILD / "flash-capacity.json"):
        shutil.copy2(source, OUT / source.name)
    manifest = {
        "purpose": "DEDICATED_DEVICE_HIL_ONLY",
        "version": identity["firmware_version"],
        "version_code": VERSION,
        "product": "A300-406",
        "ota_format": "a300-header-v1; detached signature supplied by FOTA platform",
        "release_gate": "software_pass; matching-image HIL pending",
        "runtime_gap_bytes": budget["runtime_gap"],
        "files": {path.name: {"bytes": path.stat().st_size, "sha256": digest(path)}
                  for path in sorted(OUT.iterdir()) if path.is_file()},
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                            encoding="ascii")
    (OUT / "README.txt").write_text(
        "V3.080 dedicated-device HIL package; not a production release.\n"
        "Upload OTA-A300-406-V3080-HIL.bin to the test FOTA platform as model "
        "A300-406, version code 3080. The platform supplies the detached signature.\n"
        "Use one dedicated device; do not start a fleet campaign.\n"
        "Record complete serial logs for normal OTA, power interruption, network "
        "interruption, F39/SMS load, AGNSS injection and repeated post-upgrade HEALTH.\n"
        "Require every observed F=0 and RAM_GAP>=4096, successful trial/ACTIVE "
        "and no unexplained AGNSS ACK-NAK. Match the boot version and App hash "
        "to manifest.json before considering production release.\n",
        encoding="ascii",
    )
    print(OUT)
    print(f"App SHA-256: {digest(app_target)}")
    print(f"OTA SHA-256: {digest(ota_target)}")


if __name__ == "__main__":
    main()
