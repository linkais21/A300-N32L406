from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "src/jt808.c").read_text(encoding="utf-8")

assert "static jt808_session_t s_sessions[2];" in SOURCE
assert "jt808_session_next_action(session, auth[0] != '\\0', now)" in SOURCE
assert "jt808_session_mark_sent(session, JT808_ACTION_REGISTER" in SOURCE
assert "send_register_current_identity(channel)" in SOURCE
assert "finish_frame_channel(&f, channel)" in SOURCE
assert "pending->valid = true;" in SOURCE
assert "cfg_set_auth_code(channel, pending->code)" in SOURCE
assert '"[808-RX] ch=%u msg=0x%04x sn=%u result=%u' in SOURCE
assert '"[808-RX] ch=%u bytes=%u' in SOURCE
assert '"[808-RX] ch=%u msg=0x%04x sn=%u body=%u' in SOURCE
for reason in ("SHORT", "ESCAPE", "CHECKSUM", "LENGTH", "OFFLINE"):
    assert f'drop={reason}' in SOURCE

# Diagnostics must remain metadata-only: never dump received bodies.
assert 'dbg_printf("[808-RX] data=' not in SOURCE

# Registration logs must not expose the stored authentication token.
assert '"[808] auth -> %s' not in SOURCE

print("test_jt808_registration_tx: PASS")
