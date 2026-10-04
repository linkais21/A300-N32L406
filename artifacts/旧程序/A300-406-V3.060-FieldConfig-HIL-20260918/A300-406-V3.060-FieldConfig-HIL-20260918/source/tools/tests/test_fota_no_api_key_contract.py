#!/usr/bin/env python3
"""Source contract for the original A300 OTA authentication flow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FOTA = (ROOT / "src" / "fota.c").read_text(encoding="utf-8")
PARSER = (ROOT / "src" / "fota_check_parser.c").read_text(encoding="utf-8")


def function_body(name: str) -> str:
    start = FOTA.index(name)
    brace = FOTA.index("{", start)
    depth = 0
    for index in range(brace, len(FOTA)):
        if FOTA[index] == "{":
            depth += 1
        elif FOTA[index] == "}":
            depth -= 1
            if depth == 0:
                return FOTA[brace : index + 1]
    raise AssertionError(f"unterminated function: {name}")


def main() -> int:
    assert "static bool key_valid(void)" not in FOTA
    assert "device_api_key" not in function_body("static bool send_request(void)")
    assert "device_api_key" not in function_body("int fota_start_request(")
    assert "device_api_key" not in function_body("static void begin_check(void)")
    assert '"X-Device-Key:' not in FOTA

    request = function_body("static bool send_request(void)")
    assert "Range: bytes=%lu-" in request
    assert "If-Range:" in request
    assert "Connection: close" in request
    assert '"downloadToken"' in PARSER
    assert "package_sha256" in FOTA
    assert "firmware_signature_verify" in FOTA
    print("test_fota_no_api_key_contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
