from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODEM = (ROOT / "src/ec800m.c").read_text(encoding="utf-8")


def function_body(name: str) -> str:
    start = MODEM.index(name)
    brace = MODEM.index("{", start)
    depth = 0
    for pos in range(brace, len(MODEM)):
        if MODEM[pos] == "{":
            depth += 1
        elif MODEM[pos] == "}":
            depth -= 1
            if depth == 0:
                return MODEM[brace : pos + 1]
    raise AssertionError(f"unterminated function: {name}")


netreg = function_body("static void state_machine_netreg")
init = function_body("void ec800m_init")
reset = function_body("void ec800m_reset")
urc = function_body("static void process_urc(const char *line)\n{")

# Each query round must invalidate the cached code before parsing and decide
# from this round's local result.  Responses may begin directly with +CEREG.
assert netreg.index("s_reg_status = -1;") < netreg.index('at_send_wait("AT+CEREG?"')
assert 'at_send_wait("AT+CEREG?", "OK", 2000)' in netreg
assert 'at_send_wait("AT+CGREG?", "OK", 2000)' in netreg
assert 'ec800m_parse_reg_status(s_at_resp, "+CEREG:", &status)' in netreg
assert 'ec800m_parse_reg_status(s_at_resp, "+CGREG:", &status)' in netreg
assert "reg = status == 1 || status == 5;" in netreg
assert "reg = s_reg_status == 1 || s_reg_status == 5;" not in netreg

assert "s_reg_status = -1;" in init
assert "s_reg_status = -1;" in reset
assert urc.index("pdpdeact") < urc.index("s_reg_status = -1;")

print("EC800M fresh network-registration status contract: PASS")
