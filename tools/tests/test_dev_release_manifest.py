from pathlib import Path
import argparse
import hashlib
import json


def validate(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["key_label"] == "DEV-KEY"
    assert data["mcu"] == "N32L406CBL7"
    assert data["memory"] == {"boot": [0x08000000, 0x08006000], "app": [0x08006000, 0x08020000]}
    assert isinstance(data["version_counter"], int) and data["version_counter"] > 0
    assert data["toolchain"] and data["git_revision"]
    assert isinstance(data["git_dirty"], bool)
    assert data["signature_verified"] is True
    base = path.parent
    required = {"bootloader_bin", "bootloader_elf", "bootloader_hex", "bootloader_map",
                "app_bin", "app_elf", "app_hex", "app_map", "signed_app_package", "combined_bin"}
    assert required <= data["artifacts"].keys()
    for item in data["artifacts"].values():
        assert "DEV-KEY" in item["path"]
        artifact = base / item["path"]
        blob = artifact.read_bytes()
        assert item["size"] == len(blob)
        assert item["sha256"] == hashlib.sha256(blob).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if args.manifest is None:
        root = Path(__file__).resolve().parents[2]
        builder = (root / "tools" / "build_dev_release.py").read_text(encoding="utf-8")
        assert 'LABEL="N32L406CBL7-DEV-KEY"' in builder
        assert "exist_ok=False" in builder
        assert "signature_verified" in builder and "app_vectors" in builder
    else:
        validate(args.manifest)
    print("test_dev_release_manifest: PASS")
