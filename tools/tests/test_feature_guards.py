"""Release guard for features intentionally removed from A300_406."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [ROOT / "src", ROOT / "include", ROOT / "Makefile"]
REMOVED = ("TCP_CH_NTRIP", "EC800M_CH_NTRIP", "tts_speak", "tts_stop", "GEOFENCE_MAX_ZONES", "point_in_polygon", "RTKINFO", "RTKSW")


def text_files():
    for base in SOURCES:
        if base.is_file():
            yield base
        else:
            yield from base.rglob("*.[ch]")


def run():
    haystack = {path: path.read_text(encoding="utf-8-sig", errors="ignore") for path in text_files()}
    for symbol in REMOVED:
        found = [str(path.relative_to(ROOT)) for path, text in haystack.items() if symbol in text]
        assert not found, f"removed symbol {symbol} remains in {found}"
    print("test_feature_guards: PASS")


if __name__ == "__main__":
    run()
