from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FOTA = (ROOT / "src" / "fota.c").read_text(encoding="utf-8")


required_markers = (
    '[FOTA] init',
    '[FOTA] check blocked reason=',
    '[FOTA] check begin',
    '[FOTA] tcp open attempt=',
    '[FOTA] HTTP %s sent',
    '[FOTA] check result=',
    '[FOTA] download begin',
    '[FOTA] download progress=',
    '[FOTA] install progress=',
    '[FOTA] install failed stage=header',
    '[FOTA] install failed stage=sha256',
    '[FOTA] install failed stage=signature',
    '[FOTA] install failed stage=crc',
    '[FOTA] install failed stage=vectors',
    '[FOTA] install failed stage=authorization',
    '[FOTA] install failed stage=pending',
    '[FOTA] HTTP response status=',
)

for marker in required_markers:
    assert marker in FOTA, f"missing diagnostic marker: {marker}"

assert "FOTA_DIAG_RETRY_MS" in FOTA
assert "s_diag_due" in FOTA
print("test_fota_diagnostics: PASS")
