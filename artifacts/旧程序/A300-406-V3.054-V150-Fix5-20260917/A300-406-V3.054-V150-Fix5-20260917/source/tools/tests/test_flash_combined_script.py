"""Contract and dry-run tests for production Combined programming."""

from pathlib import Path
import shutil
import struct
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "flash_combined_and_selftest.ps1"
RECORD = struct.Struct("<IHHIIIII")
EXPECTED = (0x494E4946, 1, RECORD.size, 1, 0x0F, 0xAF19BCAA, 0x52455144, 0xFFFFFFFF)


def powershell() -> str:
    executable = shutil.which("pwsh") or shutil.which("powershell")
    assert executable, "PowerShell is required"
    return executable


def make_combined(path: Path, valid_marker: bool = True) -> None:
    blob = bytearray(b"\xFF" * 0x6100)
    values = list(EXPECTED)
    if not valid_marker:
        values[-1] = 0x444F4E45
    RECORD.pack_into(blob, 0x5800, *values)
    struct.pack_into("<II", blob, 0x6000, 0x20001000, 0x08006101)
    path.write_bytes(blob)


def test_script_contract_and_dry_run():
    assert SCRIPT.exists(), f"missing wrapper: {SCRIPT}"
    source = SCRIPT.read_text(encoding="utf-8")
    for token in (
        "$TimeoutSeconds = 180", "[System.IO.Ports.SerialPort]", "115200",
        "DataBits = 8", "DtrEnable = $false", "RtsEnable = $false",
        "-e", "all", "0x08000000", "-v", "-rst", "production_selftest.py",
        "finally", "Remove-Item", "$DryRun",
    ):
        assert token in source, f"wrapper missing contract token: {token}"

    with tempfile.TemporaryDirectory(prefix="combined_flash_script_") as directory:
        temporary = Path(directory)
        combined = temporary / "Combined.bin"
        make_combined(combined)
        command = [powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass",
                   "-File", str(SCRIPT), "-CombinedPath", str(combined),
                   "-Port", "COM_TEST", "-DryRun"]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                encoding="gb18030", errors="replace")
        assert result.returncode == 0, result.stdout + result.stderr
        for stage in ("VALIDATE", "ERASE", "WRITE_VERIFY", "RESET", "SELFTEST"):
            assert stage in result.stdout

        make_combined(combined, valid_marker=False)
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                encoding="gb18030", errors="replace")
        assert result.returncode != 0
        assert "ERASE" not in result.stdout and "WRITE_VERIFY" not in result.stdout


if __name__ == "__main__":
    test_script_contract_and_dry_run()
    print("test_flash_combined_script: PASS")
