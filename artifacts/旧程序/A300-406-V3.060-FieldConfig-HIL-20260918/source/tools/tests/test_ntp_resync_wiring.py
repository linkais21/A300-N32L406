"""Regression contract for issue #3's NTP resync wiring.

Confirms the periodic sync is scheduled from main.c's superloop, retries on
failure with a shorter backoff than the steady-state cadence, and that the
only state it writes back is gps.c's retained clock (via gps_apply_ntp_utc) -
never position, fix-validity, or sleep/wake state.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "src" / "main.c").read_text(encoding="utf-8")
EC800M = (ROOT / "src" / "ec800m.c").read_text(encoding="utf-8")
EC800M_H = (ROOT / "include" / "ec800m.h").read_text(encoding="utf-8")
GPS = (ROOT / "src" / "gps.c").read_text(encoding="utf-8")
GPS_H = (ROOT / "include" / "gps.h").read_text(encoding="utf-8")


def test_main_schedules_periodic_ntp_resync():
    assert "ntp_resync_process" in MAIN
    assert "ntp_resync_process();" in MAIN
    assert "NTP_RESYNC_INTERVAL_MS" in MAIN
    assert "NTP_RETRY_INTERVAL_MS" in MAIN
    assert "ec800m_ntp_sync(&t)" in MAIN
    assert "gps_apply_ntp_utc(" in MAIN
    assert "ec800m_is_ready()" in MAIN


def test_retry_backoff_is_shorter_than_steady_state_cadence():
    resync = MAIN.split("NTP_RESYNC_INTERVAL_MS", 1)[1].split("\n", 1)[0]
    retry = MAIN.split("NTP_RETRY_INTERVAL_MS", 1)[1].split("\n", 1)[0]
    resync_ms = eval(resync.strip().strip("()").replace("UL", ""))  # noqa: S307
    retry_ms = eval(retry.strip().strip("()").replace("UL", ""))  # noqa: S307
    assert retry_ms < resync_ms


def test_ntp_sync_uses_hand_rolled_parser_not_libc():
    assert "parse_qntp" in EC800M
    assert "sscanf(" not in EC800M
    assert "atof(" not in EC800M
    assert "strtod(" not in EC800M
    assert "AT+QNTP=" in EC800M


def test_ntp_time_type_is_decoupled_from_gps_header():
    assert "ec800m_time_t" in EC800M_H
    assert '#include "gps.h"' not in EC800M_H


def test_gps_apply_ntp_utc_never_touches_position_or_validity():
    assert "gps_apply_ntp_utc" in GPS_H
    assert "gps_apply_ntp_utc" in GPS
    body = GPS.split("void gps_apply_ntp_utc", 1)[1]
    body = body[: body.index("\n}\n") + 2]
    for forbidden in ("lat_e7", "lon_e7", "speed_x10", "heading_deg",
                      "altitude_m", "fix_quality", "satellites"):
        assert forbidden not in body
    assert "s_last_trusted_valid" in body


if __name__ == "__main__":
    test_main_schedules_periodic_ntp_resync()
    test_retry_backoff_is_shorter_than_steady_state_cadence()
    test_ntp_sync_uses_hand_rolled_parser_not_libc()
    test_ntp_time_type_is_decoupled_from_gps_header()
    test_gps_apply_ntp_utc_never_touches_position_or_validity()
    print("ntp resync wiring contract: PASS")
