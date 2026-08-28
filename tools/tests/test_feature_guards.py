"""Release guards for the deliberately trimmed A300_406 production image."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE_INPUTS = (
    ROOT / "src",
    ROOT / "include",
    ROOT / "ldscript",
    ROOT / "bootloader" / "src",
    ROOT / "bootloader" / "include",
    ROOT / "bootloader" / "ldscript",
    ROOT / "Makefile",
    ROOT / "bootloader" / "Makefile",
)
RELEASE_SUFFIXES = {".c", ".h", ".s", ".ld"}
REMOVED = (
    "TCP_CH_NTRIP", "EC800M_CH_NTRIP", "tts_speak", "tts_stop",
    "GEOFENCE_MAX_ZONES", "point_in_polygon", "RTKINFO", "RTKSW",
    "ALM_VIBRATION", "WAKE_SRC_VIBRATION", "pwr_vibration_isr",
    "Baler", "BALESTAT", "BALEIDLE", "BALECLEAR", "CMCC", "C21", "Polaris",
)
FORBIDDEN_PLATFORM = re.compile(r"n32g(?:452|45x|4xx)", re.IGNORECASE)
APPROVED_ROOTS = (
    "PARAM", "DUALSET", "RESET", "PID", "IP", "FIP", "FREQ", "HBT",
    "MODEL", "SPEED", "APN", "RELAY", "GPSDUP", "MLG", "CAR", "GPSBDS",
    "GMTSET",
)
TARGET_VERSION = "T360-A300_406_20260823000000,V3.000"


def text_files():
    for base in RELEASE_INPUTS:
        if base.is_file():
            yield base
        else:
            yield from (path for path in base.rglob("*") if path.suffix.lower() in RELEASE_SUFFIXES)


def quoted_roots(source, marker):
    start = source.index(marker)
    opening = source.index("{", start)
    closing = source.index("};", opening)
    return tuple(re.findall(r'"([A-Z0-9]+)"', source[opening:closing]))


def run():
    haystack = {path: path.read_text(encoding="utf-8-sig", errors="ignore") for path in text_files()}
    for symbol in REMOVED:
        found = [str(path.relative_to(ROOT)) for path, text in haystack.items() if symbol in text]
        assert not found, f"removed symbol {symbol} remains in {found}"

    polluted = [
        str(path.relative_to(ROOT))
        for path, text in haystack.items()
        if FORBIDDEN_PLATFORM.search(str(path.relative_to(ROOT))) or FORBIDDEN_PLATFORM.search(text)
    ]
    assert not polluted, f"forbidden N32G452 platform input remains in {polluted}"

    makefile = haystack[ROOT / "Makefile"]
    assert "Nations.N32L40x_Library" in makefile
    assert "startup_n32l40x.s" in makefile and "ldscript/n32l406.ld" in makefile
    assert "src/fota.c" in makefile, "OTA source dropped from release build"

    f39_h = haystack[ROOT / "include" / "f39_command.h"]
    f39_c = haystack[ROOT / "src" / "f39_command.c"]
    sms_h = haystack[ROOT / "include" / "sms_command.h"]
    sms_c = haystack[ROOT / "src" / "sms_command.c"]
    assert quoted_roots(f39_c, "s_roots[]") == APPROVED_ROOTS
    assert quoted_roots(sms_c, "roots[]") == tuple(root for root in APPROVED_ROOTS if root != "DUALSET")
    assert re.search(r"#define\s+F39_COMMAND_MAX_LENGTH\s+191U", f39_h)
    assert "raw[F39_COMMAND_MAX_LENGTH]" in f39_h
    assert re.search(r"#define\s+SMS_COMMAND_MAX_LEN\s+192u", sms_h)
    assert re.search(r"#define\s+SMS_QUEUE_DEPTH\s+2u", sms_h)
    assert "data[SMS_COMMAND_MAX_LEN]" in sms_c

    config_h = haystack[ROOT / "include" / "config.h"]
    layout_h = haystack[ROOT / "include" / "ext_flash_layout.h"]
    fota_h = haystack[ROOT / "include" / "fota.h"]
    assert TARGET_VERSION in config_h
    assert "EXT_FLASH_BLIND_ADDR" in layout_h and "EXT_FLASH_BLIND_SIZE" in layout_h
    assert "EXT_FLASH_OWNER_BLIND_ZONE" in layout_h
    assert "FOTA_FLASH_ADDR   EXT_FLASH_CANDIDATE_ADDR" in fota_h
    assert "FOTA_PENDING_ADDR EXT_FLASH_RESUME_ADDR" in fota_h
    print("test_feature_guards: PASS")


if __name__ == "__main__":
    run()
