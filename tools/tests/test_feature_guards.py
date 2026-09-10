"""Release guards for the deliberately trimmed A300_406 production image."""
import json
import re
import tempfile
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
    "GMTSET", "VIBSENS", "FKEY", "FOTA", "LOG",
)
RELEASE_IDENTITY = json.loads(
    (ROOT / "release_identity.json").read_text(encoding="utf-8")
)
TARGET_VERSION = RELEASE_IDENTITY["firmware_version"]


def project_text_files():
    for base in RELEASE_INPUTS:
        if base.is_file():
            yield base
        else:
            yield from (path for path in base.rglob("*") if path.suffix.lower() in RELEASE_SUFFIXES)


def make_value(makefile, name):
    logical = re.sub(r"\\\r?\n\s*", " ", makefile)
    match = re.search(rf"(?m)^\s*{re.escape(name)}\s*(?::|\?)?=\s*(.*?)\s*$", logical)
    assert match, f"Makefile variable {name} is missing"
    return match.group(1)


def sdk_release_inputs(root, makefile):
    sdk_text = make_value(makefile, "SDK")
    assert "$(" not in sdk_text and "${" not in sdk_text, "SDK root must resolve directly"
    sdk_root = (root / sdk_text).resolve()

    def expand(value):
        return value.replace("$(SDK)", sdk_text).replace("${SDK}", sdk_text)

    sources = []
    for token in make_value(makefile, "C_SRCS").split():
        expanded = expand(token)
        path = (root / expanded).resolve()
        if path == sdk_root or sdk_root in path.parents:
            assert path.is_file(), f"Makefile SDK source is missing: {expanded}"
            sources.append(path)

    headers = []
    for token in make_value(makefile, "INCLUDES").split():
        if not token.startswith("-I"):
            continue
        expanded = expand(token[2:])
        path = (root / expanded).resolve()
        if path == sdk_root or sdk_root in path.parents:
            assert path.is_dir(), f"Makefile SDK include directory is missing: {expanded}"
            headers.extend(candidate for candidate in path.rglob("*.h") if candidate.is_file())

    assert sources, "Makefile has no compiled SDK source inputs"
    assert headers, "Makefile has no SDK header inputs"
    return tuple(dict.fromkeys(sources + headers))


def platform_findings(paths):
    findings = []
    for path in paths:
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
        if FORBIDDEN_PLATFORM.search(str(path)) or FORBIDDEN_PLATFORM.search(text):
            findings.append(path)
    return findings


def quoted_roots(source, marker):
    start = source.index(marker)
    opening = source.index("{", start)
    closing = source.index("};", opening)
    return tuple(re.findall(r'"([A-Z0-9]+)"', source[opening:closing]))


def regression_forbidden_sdk_input_is_rejected():
    """A forbidden token in a compiled SDK input must fail the platform scan."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        sdk_source = root / "sdk" / "firmware" / "CMSIS" / "device" / "system_n32l40x.c"
        sdk_header = root / "sdk" / "firmware" / "CMSIS" / "core" / "core_cm4.h"
        sdk_source.parent.mkdir(parents=True)
        sdk_header.parent.mkdir(parents=True)
        makefile = (
            "SDK := sdk/firmware\n"
            "C_SRCS := $(SDK)/CMSIS/device/system_n32l40x.c\n"
            "INCLUDES := -I$(SDK)/CMSIS/core\n"
        )
        sdk_source.write_text("/* Cortex-M4 */\n", encoding="ascii")
        sdk_header.write_text("/* Cortex-M4 */\n", encoding="ascii")
        inputs = sdk_release_inputs(root, makefile)
        assert sdk_source in inputs, "compiled SDK source was not derived from Makefile"
        assert sdk_header in inputs, "SDK include header was not derived from Makefile"
        for token, polluted_input in (
            ("N32G452", sdk_source),
            ("N32G45x", sdk_header),
            ("N32G4xx", sdk_source),
        ):
            sdk_source.write_text("/* Cortex-M4 */\n", encoding="ascii")
            sdk_header.write_text("/* Cortex-M4 */\n", encoding="ascii")
            polluted_input.write_text(f"/* copied {token} platform */\n", encoding="ascii")
            assert platform_findings(inputs) == [polluted_input], f"{token} pollution was not rejected"


def run():
    regression_forbidden_sdk_input_is_rejected()
    project_files = tuple(project_text_files())
    haystack = {path: path.read_text(encoding="utf-8-sig", errors="ignore") for path in project_files}
    for symbol in REMOVED:
        found = [str(path.relative_to(ROOT)) for path, text in haystack.items() if symbol in text]
        assert not found, f"removed symbol {symbol} remains in {found}"

    makefile = haystack[ROOT / "Makefile"]
    sdk_files = sdk_release_inputs(ROOT, makefile)
    polluted = [str(path.relative_to(ROOT)) for path in platform_findings(project_files + sdk_files)]
    assert not polluted, f"forbidden N32G452 platform input remains in {polluted}"

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
    assert RELEASE_IDENTITY["ota_device_model"] in config_h
    assert RELEASE_IDENTITY["jt808_terminal_model"] in config_h
    assert RELEASE_IDENTITY["jt808_manufacturer_id"] in config_h
    assert "EXT_FLASH_BLIND_ADDR" in layout_h and "EXT_FLASH_BLIND_SIZE" in layout_h
    assert "EXT_FLASH_OWNER_BLIND_ZONE" in layout_h
    assert "FOTA_FLASH_ADDR   EXT_FLASH_CANDIDATE_ADDR" in fota_h
    assert "FOTA_PENDING_ADDR EXT_FLASH_RESUME_ADDR" in fota_h
    print("test_feature_guards: PASS")


if __name__ == "__main__":
    run()
