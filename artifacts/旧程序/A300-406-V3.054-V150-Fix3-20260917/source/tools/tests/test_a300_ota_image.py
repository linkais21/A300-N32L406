from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zlib


ROOT = Path(__file__).resolve().parents[2]
HEADER = struct.Struct("<IIIII12s")


def test_generator_builds_a300_compatible_unsigned_package() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        body = bytes(range(251)) * 3
        source = work / "app.bin"
        output = work / "ota.bin"
        source.write_bytes(body)
        subprocess.run([
            sys.executable, str(ROOT / "tools" / "gen_a300_ota_image.py"),
            "--input", str(source), "--output", str(output),
            "--version-code", "3001",
        ], check=True, capture_output=True, text=True)
        package = output.read_bytes()
        assert len(package) == HEADER.size + len(body)
        magic, version, size, body_crc, product, reserved = HEADER.unpack_from(package)
        assert (magic, version, size, product) == (0xA300B007, 3001, len(body), 0x41333030)
        assert body_crc == zlib.crc32(body) & 0xFFFFFFFF
        assert reserved == bytes(12)
        assert package[HEADER.size:] == body


def test_generator_rejects_unbootable_or_oversized_app() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        for name, body in (
            ("short", bytes(7)),
            ("oversized", bytes(106497)),
        ):
            source = work / f"{name}.bin"
            source.write_bytes(body)
            result = subprocess.run([
                sys.executable, str(ROOT / "tools" / "gen_a300_ota_image.py"),
                "--input", str(source), "--output", str(work / f"{name}.ota.bin"),
                "--version-code", "3001",
            ], capture_output=True, text=True)
            assert result.returncode != 0


if __name__ == "__main__":
    test_generator_builds_a300_compatible_unsigned_package()
    test_generator_rejects_unbootable_or_oversized_app()
    print("test_a300_ota_image: PASS")
