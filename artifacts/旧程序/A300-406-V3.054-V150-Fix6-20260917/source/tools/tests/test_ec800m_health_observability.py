from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEADER = (ROOT / "include/ec800m.h").read_text(encoding="utf-8")
MODEM = (ROOT / "src/ec800m.c").read_text(encoding="utf-8")
MAIN = (ROOT / "src/main.c").read_text(encoding="utf-8")

for token in (
    "EC800M_FAILURE_NONE",
    "EC800M_FAILURE_SIM_QUERY",
    "EC800M_FAILURE_NETREG_QUERY",
    "EC800M_FAILURE_PDP_ACTIVATE",
    "EC800M_FAILURE_PDP_QUERY",
    "ec800m_get_failure",
    "ec800m_state_name",
    "ec800m_failure_name",
    "ec800m_get_reg_status",
):
    assert token in HEADER

assert "EC800M_DIAG_INTERVAL_MS 10000U" in MODEM
assert 'at_send_wait("AT+CEREG?", "OK", 2000)' in MODEM
assert 'ec800m_parse_reg_status(s_at_resp, "+CEREG:", &status)' in MODEM
assert 'at_send_wait("AT+CGREG?", "OK", 2000)' in MODEM
assert 'ec800m_parse_reg_status(s_at_resp, "+CGREG:", &status)' in MODEM
assert "[4G] state=%s reason=%s reg=%d" in MODEM
assert "s_last_diag_ms" in MODEM
for reason in ("SIM_QUERY", "NETREG_QUERY", "PDP_ACTIVATE", "PDP_QUERY"):
    assert reason in MODEM

assert "[HEALTH] 4G=%u S=%s R=%s REG=%d GPS=%u" in MAIN
assert "ec800m_state_name(ec800m_get_state())" in MAIN
assert "ec800m_failure_name(ec800m_get_failure())" in MAIN
assert "ec800m_get_reg_status()" in MAIN

print("EC800M health observability contract: PASS")
