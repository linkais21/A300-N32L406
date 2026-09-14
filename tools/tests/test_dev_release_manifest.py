import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def validate(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    identity = json.loads((Path(__file__).resolve().parents[2] / "release_identity.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["signing"] == "platform-detached"
    assert data["mcu"] == "N32L406CBL7"
    assert data["memory"] == {"boot": [0x08000000, 0x08006000], "app": [0x08006000, 0x08020000]}
    assert data["version_counter"] == identity["firmware_version_counter"]
    assert data["toolchain"] and data["git_revision"]
    assert isinstance(data["git_dirty"], bool)
    assert data["ota_format"] == "a300-header-v1"
    base = path.parent
    expected_label = "V" + identity["firmware_version"].rsplit("V", 1)[1]
    assert base.name == expected_label
    required = {"bootloader_bin", "bootloader_elf", "bootloader_hex", "bootloader_map",
                "app_bin", "app_elf", "app_hex", "app_map", "ota_upload_bin", "combined_bin"}
    assert required <= data["artifacts"].keys()
    for item in data["artifacts"].values():
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
        identity = json.loads((root / "release_identity.json").read_text(encoding="utf-8"))
        assert 'LABEL="N32L406CBL7"' in builder
        assert 'ROOT / ".toolchain" / "bin"' in builder
        assert "D:\\\\ST\\\\STM32CubeIDE" not in builder
        assert '"TOOLCHAIN_ROOT=" + str(TOOLCHAIN)' in builder
        assert 'default=ROOT/"artifacts"' in builder
        assert "exist_ok=False" in builder
        assert "build_id" not in builder
        assert 'strftime("%Y%m%dT%H%M%SZ")' not in builder
        assert "platform-detached" in builder and "app_vectors" in builder
        assert "validate_factory_init_marker" in builder
        assert "build_combined" in builder
        mismatch = subprocess.run(
            [sys.executable, "tools/build_dev_release.py",
             "--version-counter", str(identity["firmware_version_counter"] + 1)],
            cwd=root,
            capture_output=True,
            text=True,
        )
        assert mismatch.returncode == 2
        assert "must match release_identity.json" in mismatch.stderr

        spec = importlib.util.spec_from_file_location("build_dev_release", root / "tools" / "build_dev_release.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        expected_label = "V" + identity["firmware_version"].rsplit("V", 1)[1]
        assert module.release_version_label(identity) == expected_label
        assert module.release_output_dir(Path("artifacts"), identity) == Path("artifacts") / expected_label
        for malformed in (
            {},
            {"firmware_version": "V3.002-extra"},
            {"firmware_version": "T360-A300_406_20260823000000,3.002"},
        ):
            try:
                module.release_version_label(malformed)
            except ValueError as exc:
                assert "firmware_version" in str(exc)
            else:
                raise AssertionError(f"malformed version accepted: {malformed!r}")
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "artifacts"
            release_dir = module.reserve_release_dir(output_root, identity)
            assert release_dir == output_root / expected_label
            sentinel = release_dir / "existing.bin"
            sentinel.write_bytes(b"do-not-overwrite")
            try:
                module.reserve_release_dir(output_root, identity)
            except FileExistsError:
                pass
            else:
                raise AssertionError("existing version directory was accepted")
            assert sentinel.read_bytes() == b"do-not-overwrite"
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            module.ROOT = temporary_root
            for invalid_counter in (True, False):
                (temporary_root / "release_identity.json").write_text(
                    json.dumps({
                        "firmware_version": identity["firmware_version"],
                        "firmware_version_counter": invalid_counter,
                    }) + "\n",
                    encoding="utf-8",
                )
                try:
                    module.release_identity()
                except ValueError as exc:
                    assert "firmware_version_counter" in str(exc)
                else:
                    raise AssertionError(f"boolean counter {invalid_counter} was accepted")
    else:
        validate(args.manifest)
    print("test_dev_release_manifest: PASS")
