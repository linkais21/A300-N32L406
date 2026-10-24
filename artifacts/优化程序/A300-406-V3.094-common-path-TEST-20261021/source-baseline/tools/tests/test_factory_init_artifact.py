"""Validate the one-time factory-init record in Bootloader and Combined artifacts."""

import importlib.util
from pathlib import Path
import struct
import subprocess


ROOT = Path(__file__).resolve().parents[2]
FACTORY_OFFSET = 0x5800
APP_OFFSET = 0x6000
RECORD = struct.Struct("<IHHIIIII")
EXPECTED = (0x494E4946, 1, RECORD.size, 1, 0x0F, 0xAF19BCAA, 0x52455144, 0xFFFFFFFF)


def load_builder():
    path = ROOT / "tools" / "build_dev_release.py"
    spec = importlib.util.spec_from_file_location("build_dev_release_factory_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def valid_app() -> bytes:
    blob = bytearray(b"\xFF" * 64)
    struct.pack_into("<II", blob, 0, 0x20001000, 0x08006101)
    return bytes(blob)


def test_builder_contract():
    builder = load_builder()
    boot = bytearray(b"\xFF" * APP_OFFSET)
    RECORD.pack_into(boot, FACTORY_OFFSET, *EXPECTED)

    assert builder.validate_factory_init_marker(bytes(boot), "test boot") == EXPECTED
    combined = builder.build_combined(bytes(boot), valid_app())
    assert len(combined) == APP_OFFSET + len(valid_app())
    assert RECORD.unpack_from(combined, FACTORY_OFFSET) == EXPECTED
    assert combined[APP_OFFSET:] == valid_app()

    for field in range(len(EXPECTED)):
        corrupt = bytearray(boot)
        values = list(EXPECTED)
        values[field] ^= 1
        RECORD.pack_into(corrupt, FACTORY_OFFSET, *values)
        try:
            builder.validate_factory_init_marker(bytes(corrupt), "corrupt boot")
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"corrupt factory-init field {field} was accepted")

    try:
        builder.validate_factory_init_marker(bytes(boot[:FACTORY_OFFSET + RECORD.size - 1]), "short boot")
    except RuntimeError:
        pass
    else:
        raise AssertionError("truncated factory-init record was accepted")

    invalid_app = bytearray(valid_app())
    struct.pack_into("<I", invalid_app, 4, 0x08006100)
    try:
        builder.build_combined(bytes(boot), bytes(invalid_app))
    except RuntimeError:
        pass
    else:
        raise AssertionError("Combined with invalid App vectors was accepted")


def test_real_bootloader_section_and_binary():
    elf = ROOT / "bootloader" / "build" / "bootloader.elf"
    binary = ROOT / "bootloader" / "build" / "bootloader.bin"
    objdump = ROOT / ".toolchain" / "bin" / "arm-none-eabi-objdump.exe"
    assert elf.is_file() and binary.is_file(), "build Bootloader before artifact validation"
    result = subprocess.run([str(objdump), "-h", str(elf)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert ".factory_init_request 0000001c  08005800" in result.stdout
    assert RECORD.unpack_from(binary.read_bytes(), FACTORY_OFFSET) == EXPECTED


if __name__ == "__main__":
    test_builder_contract()
    test_real_bootloader_section_and_binary()
    print("test_factory_init_artifact: PASS")
