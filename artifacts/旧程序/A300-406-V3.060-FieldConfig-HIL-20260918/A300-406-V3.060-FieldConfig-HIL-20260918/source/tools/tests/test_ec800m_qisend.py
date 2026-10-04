from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "src/ec800m.c").read_text(encoding="utf-8")

assert "static bool at_wait_prompt_owned(" in SOURCE
assert "if (c == '>')" in SOURCE
assert 'dbg_printf("[4G-TX] ch=%u len=%u' in SOURCE
for stage in ("prompt", "payload", "result"):
    assert f'fail stage={stage}' in SOURCE
assert 'dbg_printf("[4G-TX] ch=%u SEND OK' in SOURCE

function = SOURCE.split("int ec800m_tcp_send(", 1)[1].split("int ec800m_udp_send_once", 1)[0]
assert "goto done;" in function
assert function.count("at_owner_release(AT_OWNER_TCP)") == 1
assert 'dbg_printf("[4G-TX]"' not in function or "%s" not in function

print("test_ec800m_qisend: PASS")
