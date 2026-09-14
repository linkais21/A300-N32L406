"""Tests for sanitized production startup-log grading."""

from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "production_selftest.py"

BASE = """\
[BOOT] ready
[FLASH] JEDEC=684015 SR1=00 SR2=00 SR3=00
[4G] ready
[808] ch0 ONLINE
[HEALTH] 4G=1 S=READY R=NONE REG=1 GPS=0 HEAP_USED=1
[GPS] RX=800 SENT=4 GGA=2 RMC=2 OK=4 CS=0 FMT=0 NOFIX=4 DROP=0
"""


def run_log(log: str) -> subprocess.CompletedProcess[str]:
    assert SCRIPT.exists(), f"missing parser: {SCRIPT}"
    with tempfile.TemporaryDirectory(prefix="production_selftest_") as directory:
        path = Path(directory) / "capture.log"
        path.write_text(log, encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(path)], cwd=ROOT,
            capture_output=True, text=True,
        )


def test_success_and_optional_results():
    result = run_log(BASE)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CORE=PASS" in result.stdout and "GNSS=NO_FIX" in result.stdout

    fixed = BASE.replace("GPS=0", "GPS=1")
    result = run_log(fixed)
    assert result.returncode == 0
    assert "GNSS=FIX" in result.stdout

    warning = BASE + "[FOTA] HTTP response status=401 op=1\n"
    result = run_log(warning)
    assert result.returncode == 0
    assert "FOTA_401" in result.stdout


def test_each_mandatory_stage_and_counter_failure():
    tokens = ("[BOOT] ready", "JEDEC=684015", "[4G] ready", "[808] ch0 ONLINE", "[GPS]")
    for token in tokens:
        result = run_log("\n".join(line for line in BASE.splitlines() if token not in line))
        assert result.returncode != 0, (token, result.stdout, result.stderr)
        assert "CORE=FAIL" in result.stdout

    replacements = (
        ("RX=800", "RX=0"),
        ("GGA=2", "GGA=0"),
        ("RMC=2", "RMC=0"),
        ("CS=0", "CS=1"),
        ("FMT=0", "FMT=1"),
        ("RX=800", "RX=bad"),
    )
    for old, new in replacements:
        result = run_log(BASE.replace(old, new))
        assert result.returncode != 0, (new, result.stdout, result.stderr)


def test_sensitive_values_are_never_echoed():
    secrets = (
        "867530912345678", "89860412345678901234", "31.230416", "121.473701",
        "203.0.113.42", "X-Device-Key=super-secret-device-key",
    )
    result = run_log(BASE + "\n".join(secrets) + "\n")
    output = result.stdout + result.stderr
    assert result.returncode == 0
    for secret in secrets:
        assert secret not in output


if __name__ == "__main__":
    test_success_and_optional_results()
    test_each_mandatory_stage_and_counter_failure()
    test_sensitive_values_are_never_echoed()
    print("test_production_selftest: PASS")
