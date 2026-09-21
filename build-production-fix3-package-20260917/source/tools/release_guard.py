#!/usr/bin/env python3
"""Reject legacy product/version identifiers in release-controlled files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

FORBIDDEN = ("T663B", "A300_202511", "V1.274")
ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "release_identity.json").read_text(encoding="utf-8"))
TARGET_VERSION = CONTRACT["firmware_version"]
TARGET_VERSION_COUNTER = CONTRACT["firmware_version_counter"]
TARGET_OTA_MODEL = CONTRACT["ota_device_model"]
TARGET_JT808_MODEL = CONTRACT["jt808_terminal_model"]
TARGET_MANUFACTURER_ID = CONTRACT["jt808_manufacturer_id"]
DEFAULT_PATHS = (
    "src",
    "include",
    "ldscript",
    "bootloader",
    "firmware",
    "manifest.json",
    "manifest.yaml",
    "manifest.yml",
    "packaging",
    "gen_version.ps1",
    "release_identity.json",
)

IDENTITY_CONSUMERS = (
    "src/main.c", "src/jt808.c", "src/jt808_params.c", "src/terminal_identity.c",
    "src/jt808_terminal_info.c", "src/f39_reply.c",
)
SEVEN_BYTE_LITERAL = re.compile(r'"([A-Za-z0-9]{7})"')
STRING_LITERAL = re.compile(r'"([A-Za-z0-9]*)"')
CHAR_LITERAL = re.compile(r"^(?:L|u|U)?'((?:\\.|[^\\'])+)'$")
INTEGER_LITERAL = re.compile(
    r"^(0[xX][0-9A-Fa-f]+|0[0-7]*|[1-9][0-9]*)(?:[uU](?:[lL]{1,2})?|[lL]{1,2}[uU]?)?$"
)
# "DUALSET"/"VIBSENS" are seven-character SMS command names from the terminal
# command spec, not hardcoded seven-byte JT808 terminal ids.
IDENTITY_LITERAL_ALLOWLIST = {"DUALSET", "VIBSENS", "invalid"}
IDENTITY_SERVICE_REQUIREMENTS = {
    "src/main.c": ("main", re.compile(
        r"\bs_terminal\.terminal_id\s*\[\s*0\s*\]\s*=\s*'\\0'\s*;"
    ), None, ()),
    "src/jt808.c": ("refresh_terminal_identity", re.compile(
        r"terminal_identity_sync\s*\(\s*pid\s*,\s*phone\s*,\s*terminal_id\s*\)"
    ), "terminal_id", (
        re.compile(r"char\s+pid\s*\[\s*12\s*\]\s*,\s*phone\s*\[\s*13\s*\]\s*,\s*terminal_id\s*\[\s*8\s*\]\s*;"),
        re.compile(r"terminal_identity_sync\s*\(\s*pid\s*,\s*phone\s*,\s*terminal_id\s*\)"),
        re.compile(r"memcpy\s*\(\s*s_term\.terminal_id\s*,\s*terminal_id\s*,"
                   r"\s*sizeof\s*\(\s*s_term\.terminal_id\s*\)\s*\)"),
    )),
    "src/jt808_params.c": ("jt808_params_handle_info_query", re.compile(
        r"jt808_terminal_info_encode\s*\(\s*body\s*,\s*sizeof\s*\(\s*body\s*\)\s*,\s*&length\s*\)"
    ), None, ()),
    "src/jt808_terminal_info.c": ("jt808_terminal_info_encode", re.compile(
        r"terminal_identity_load\s*\(\s*terminal_id\s*\)"
    ), "terminal_id", (
        re.compile(r"char\s+terminal_id\s*\[\s*8\s*\]\s*;"),
        re.compile(r"terminal_identity_load\s*\(\s*terminal_id\s*\)"),
        re.compile(r"memcpy\s*\(\s*body\s*\+\s*position\s*,\s*terminal_id\s*,\s*7U\s*\)"),
    )),
    "src/terminal_identity.c": ("terminal_identity_load", re.compile(
        r"return\s+terminal_identity_sync\s*\(\s*pid\s*,\s*phone\s*,\s*out\s*\)\s*;"
    ), "out", (
        re.compile(r"char\s+pid\s*\[\s*12\s*\]\s*;"),
        re.compile(r"char\s+phone\s*\[\s*13\s*\]\s*;"),
        re.compile(r"return\s+terminal_identity_sync\s*\(\s*pid\s*,\s*phone\s*,\s*out\s*\)\s*;"),
    )),
    "src/f39_reply.c": ("device_id", re.compile(
        r"return\s+terminal_id_derive\s*\(\s*c->pid\s*,\s*imei\s*,\s*terminal_id\s*\)\s*;"
    ), "terminal_id", (
        re.compile(r"return\s+terminal_id_derive\s*\(\s*c->pid\s*,\s*imei\s*,\s*terminal_id\s*\)\s*;"),
    )),
}
CANONICAL_CONSUMER_PATTERNS = {
    "src/main.c": (
        re.compile(r"s_terminal\.terminal_id\s*\[\s*0\s*\]\s*=\s*'\\0'\s*;"),
    ),
    "src/jt808.c": (
        re.compile(r"char\s+pid\s*\[\s*12\s*\]\s*,\s*phone\s*\[\s*13\s*\]\s*,\s*terminal_id\s*\[\s*8\s*\]\s*;"),
        re.compile(r"if\s*\(\s*!terminal_identity_sync\s*\(\s*pid\s*,\s*phone\s*,\s*terminal_id\s*\)\s*\)\s*return\s+false\s*;"),
        re.compile(r"memcpy\s*\(\s*s_term\.terminal_id\s*,\s*terminal_id\s*,\s*"
                   r"sizeof\s*\(\s*s_term\.terminal_id\s*\)\s*\)\s*;"),
        re.compile(r"return\s+true\s*;"),
    ),
    "src/jt808_params.c": (
        re.compile(r"uint8_t\s+body\s*\[\s*JT808_TERMINAL_INFO_BODY_LENGTH\s*\]\s*;"),
        re.compile(r"jt808_terminal_info_encode\s*\(\s*body\s*,\s*sizeof\s*\(\s*body\s*\)\s*,\s*&length\s*\)"),
        re.compile(r"jt808_send_raw\s*\(\s*0x0107U\s*,\s*sn\s*,\s*body\s*,\s*length\s*\)\s*;"),
    ),
    "src/jt808_terminal_info.c": (
        re.compile(r"char\s+terminal_id\s*\[\s*8\s*\]\s*;"),
        re.compile(r"if\s*\(\s*!terminal_identity_load\s*\(\s*terminal_id\s*\)\s*\)"),
        re.compile(r"memcpy\s*\(\s*body\s*\+\s*position\s*,\s*terminal_id\s*,\s*7U\s*\)\s*;"),
    ),
    "src/terminal_identity.c": (
        re.compile(r"char\s+pid\s*\[\s*12\s*\]\s*;"),
        re.compile(r"char\s+phone\s*\[\s*13\s*\]\s*;"),
        re.compile(r"return\s+terminal_identity_sync\s*\(\s*pid\s*,\s*phone\s*,\s*out\s*\)\s*;"),
    ),
    "src/f39_reply.c": (
        re.compile(r"char\s+imei\s*\[\s*F39_IMEI_MAX_LENGTH\s*\+\s*1U\s*\]\s*;"),
        re.compile(r"return\s+terminal_id_derive\s*\(\s*c->pid\s*,\s*imei\s*,\s*terminal_id\s*\)\s*;"),
    ),
}
CANONICAL_CONSUMER_MACROS = {
    "src/main.c": {"FW_BUILD_DATE", "FW_BUILD_NUMBER", "FW_FULL_VERSION", "FW_JT808_MODEL_STR",
                   "FW_MANUFACTURER_ID_STR", "WORK_MODE_DEFAULT_STOPPED_REPORT_S",
                   "TICK_MS"},
    "src/jt808_params.c": {"JT808_TERMINAL_INFO_BODY_LENGTH",
                            "MSG_QUERY_TERMINAL_INFO"},
    "src/jt808_terminal_info.c": {"FW_VERSION_STR", "FW_JT808_MODEL_STR",
                                    "FW_MANUFACTURER_ID_STR",
                                    "JT808_TERMINAL_INFO_BODY_LENGTH"},
    "src/f39_reply.c": {"F39_IMEI_MAX_LENGTH"},
}
CANONICAL_MACRO_DEFINITIONS = {
    "FW_BUILD_DATE": re.compile(r'"[^"\r\n]*"'),
    "FW_BUILD_NUMBER": re.compile(r'"[0-9]{12}"'),
    "FW_FULL_VERSION": re.compile(rf'"{re.escape(TARGET_VERSION)}"'),
    "FW_OTA_MODEL_STR": re.compile(rf'"{re.escape(TARGET_OTA_MODEL)}"'),
    "FW_JT808_MODEL_STR": re.compile(rf'"{re.escape(TARGET_JT808_MODEL)}"'),
    "FW_MANUFACTURER_ID_STR": re.compile(rf'"{re.escape(TARGET_MANUFACTURER_ID)}"'),
    "JT808_TERMINAL_INFO_BODY_LENGTH": re.compile(r"83(?:[uU])?"),
    "FW_VERSION_STR": re.compile(rf'"{re.escape(TARGET_VERSION)}"'),
    "MSG_QUERY_TERMINAL_INFO": re.compile(r"0[xX]8107(?:[uUlL]*)"),
    "F39_IMEI_MAX_LENGTH": re.compile(r"15(?:[uU])?"),
    "WORK_MODE_DEFAULT_STOPPED_REPORT_S": re.compile(r"180(?:[uU])?"),
    "TICK_MS": re.compile(r"\(\s*g_tick_ms\s*\)"),
}
C_IDENTIFIER = r"(?:[^\W\d]|\\(?:u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}))(?:\w|\\(?:u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}))*"
PP_DIRECTIVE = r"(?:#|%:|\?\?=)"
TRIGRAPHS = {
    "??=": "#", "??/": "\\", "??'": "^", "??(": "[", "??)": "]",
    "??!": "|", "??<": "{", "??>": "}", "??-": "~",
}
CANONICAL_CONSUMER_SHA256 = {
    # Reviewed: startup display uses compile timestamp, semantic version stays canonical.
    "src/main.c": "a5ad3e8d0eaba8cc46bcd2e9587c6b22f601f800faf748ef503f1bc5aa96738a",
    "src/jt808.c": "d38583fc4d2e47eab4fe184b90a21205dc6e2606266a20e824bff69321871586",
    "src/jt808_params.c": "2f4c5cefaa334a336896ec36cc7feaaa56ae1b56dcaef44e4b33a33008dc7a11",
    "src/jt808_terminal_info.c": "0ce1a9cf82880062c0d84b88bc50ae047c59ec7f6e5e17ea59266b50a0499d49",
    "src/terminal_identity.c": "d8f0d206632b5ecb436d0989e3e9daf8a7fbb734763446a84e27285b3e261d5b",
    "src/f39_reply.c": "19e1722a06a1a1c78e38ab9ec0902ee5b7821d6e0d6cdf93035cd6c5758bc3ce",
}
CANONICAL_IDENTITY_FILE_SHA256 = {
    "include/config.h": "d9d2708db6a0d87a035ac16826a66695a0a7f1f17ca4e46b6b7d2d99db948cad",
    "include/build_version.h": "f936408a2f3ae64d080f67b98ea1d1866b621544212a567365c3895860e05052",
    "include/f39_reply.h": "2ed804411ce7eaac804a739764824fd0c4e73342744ea63240a728a2e46f8715",
    # Reviewed addition: 0x8106 ID and existing plate encoder declaration only.
    "include/jt808.h": "eca870809ad6a9749b364754e2a5aa2c73c919cb3df3b3a0fe3394ea9e76f786",
    "include/jt808_terminal_info.h": "ed27611b540da8fe8ed50a3d349d52ada04f2e66aa62db8f3d6b85497c35d8df",
}


def strip_c_comments(text: str) -> str:
    translated = text
    for trigraph, replacement in TRIGRAPHS.items():
        translated = translated.replace(trigraph, replacement)
    spliced = re.sub(r"\\\r?\n", "", translated)
    result = []
    index = 0
    quote = None
    escaped = False
    while index < len(spliced):
        char = spliced[index]
        following = spliced[index + 1] if index + 1 < len(spliced) else ""
        if quote is not None:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
        elif char in ("'", '"'):
            quote = char
            result.append(char)
            index += 1
        elif char == "/" and following == "/":
            index += 2
            while index < len(spliced) and spliced[index] not in "\r\n":
                index += 1
        elif char == "/" and following == "*":
            index += 2
            while index + 1 < len(spliced) and spliced[index:index + 2] != "*/":
                if spliced[index] in "\r\n":
                    result.append(spliced[index])
                index += 1
            index = min(index + 2, len(spliced))
        else:
            result.append(char)
            index += 1
    return "".join(result)


def fixed_identity_findings(text: str):
    """Return seven-byte alphanumeric literals from an identity consumer."""
    clean = strip_c_comments(text)
    findings = [match.group(1) for match in SEVEN_BYTE_LITERAL.finditer(clean)]

    literals = list(STRING_LITERAL.finditer(clean))
    run = ""
    count = 0
    previous_end = 0
    for match in literals:
        if count > 0 and clean[previous_end:match.start()].strip() == "":
            run += match.group(1)
            count += 1
        else:
            run = match.group(1)
            count = 1
        if count >= 2 and len(run) == 7 and run.isalnum():
            findings.append(run)
        previous_end = match.end()

    for initializer in re.finditer(r"\{([^{}]*)\}", clean, flags=re.DOTALL):
        values = []
        valid = True
        for token in initializer.group(1).split(","):
            token = unwrap_c_integer_constant(token)
            char_match = CHAR_LITERAL.match(token)
            if char_match:
                value = c_character_value(char_match.group(1))
                if value is None:
                    valid = False
                    break
                values.append(value)
            else:
                integer_match = INTEGER_LITERAL.match(token)
                if integer_match:
                    values.append(c_integer_value(integer_match.group(1)))
                else:
                    valid = False
                    break
        if valid and len(values) in (7, 8) and all(chr(value).isascii() and chr(value).isalnum()
                                                     for value in values[:7]):
            if len(values) == 7 or values[7] == 0:
                findings.append("".join(chr(value) for value in values[:7]))
    return findings


def unwrap_c_integer_constant(token: str) -> str:
    """Remove redundant parens and common integer casts around one constant."""
    token = token.strip()
    cast = re.compile(
        r"^\(\s*(?:(?:(?:signed|unsigned)\s+)?(?:char|short|int|long(?:\s+long)?)"
        r"|(?:u?int(?:8|16|32|64)_t|size_t))\s*\)\s*",
        re.IGNORECASE,
    )
    while True:
        previous = token
        if token.startswith("(") and token.endswith(")") and c_outer_parens_wrap(token):
            token = token[1:-1].strip()
        token = cast.sub("", token, count=1).strip()
        if token == previous:
            return token


def c_outer_parens_wrap(token: str) -> bool:
    depth = 0
    quote = None
    escaped = False
    for index, char in enumerate(token):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and index != len(token) - 1:
                return False
    return depth == 0


def c_character_value(content: str) -> int | None:
    """Decode one ordinary, octal, hex, or simple escaped C character."""
    if len(content) == 1 and content != "\\":
        return ord(content)
    if not content.startswith("\\"):
        return None
    escape = content[1:]
    simple = {
        "a": 0x07, "b": 0x08, "f": 0x0C, "n": 0x0A, "r": 0x0D,
        "t": 0x09, "v": 0x0B, "\\": 0x5C, "'": 0x27, '"': 0x22,
        "?": 0x3F,
    }
    if escape in simple:
        return simple[escape]
    if re.fullmatch(r"[0-7]{1,3}", escape):
        return int(escape, 8)
    if re.fullmatch(r"x[0-9A-Fa-f]+", escape):
        return int(escape[1:], 16)
    return None


def c_integer_value(spelling: str) -> int:
    """Decode the suffix-free spelling captured by INTEGER_LITERAL."""
    if spelling.lower().startswith("0x"):
        return int(spelling[2:], 16)
    if len(spelling) > 1 and spelling.startswith("0"):
        return int(spelling[1:], 8)
    return int(spelling, 10)


def c_function_body(text: str, name: str) -> str | None:
    """Return one named C function body without crossing its closing brace."""
    clean = strip_c_comments(text)
    match = re.search(rf"\b{re.escape(name)}\s*\([^;{{}}]*\)\s*\{{", clean)
    if match is None:
        return None
    start = match.end()
    depth = 1
    quote = None
    escaped = False
    for index in range(start, len(clean)):
        char = clean[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return clean[start:index]
    return None


def canonical_body_digest(body: str) -> str:
    """Hash a comment-free body after stable newline/trailing-space normalization."""
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n")).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def canonical_file_digest(text: str, relative: str) -> str:
    """Hash reviewed dependency text, ignoring generator-only volatile fields."""
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if relative == "include/build_version.h":
        normalized = re.sub(
            r"\A/\* Auto-generated build version - DO NOT EDIT \*/\n",
            "",
            normalized,
        )
        normalized = re.sub(
            r'(?m)^(\s*#define\s+FW_BUILD_(?:NUMBER|DATE)\s+)"[^"\r\n]*"\s*$',
            r'\1"<generated>"',
            normalized,
        )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def canonical_identity_consumer(text: str, relative: str, function_name: str,
                                body: str, macro_names: set[str] | None = None,
                                macro_definitions: dict[str, list[str]] | None = None) -> str | None:
    """Return a reason when one small consumer departs from its strict contract."""
    clean = strip_c_comments(text)
    if canonical_body_digest(body) != CANONICAL_CONSUMER_SHA256.get(relative):
        return f"noncanonical body for {function_name}() consumer; manual review required"
    if re.search(rf"(?m){PP_DIRECTIVE}\s*{C_IDENTIFIER}", body):
        return f"preprocessor directive forbidden for {function_name}() consumer"
    if re.search(r"[^\x00-\x7f]|\\(?:u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8})", body):
        return f"non-ASCII identifier forbidden for {function_name}() consumer"
    local_macro_names = set(re.findall(
        rf"(?m)^\s*{PP_DIRECTIVE}\s*define\s+({C_IDENTIFIER})(?:\([^\r\n)]*\))?", clean
    ))
    if macro_names is not None:
        local_macro_names.update(macro_names)
    allowed_macros = CANONICAL_CONSUMER_MACROS.get(relative, set())
    if macro_definitions is not None:
        for name in allowed_macros:
            definitions = macro_definitions.get(name, [])
            expected = CANONICAL_MACRO_DEFINITIONS[name]
            if len(definitions) != 1 or expected.fullmatch(definitions[0].strip()) is None:
                return f"noncanonical definition for allowed macro {name}"
    forbidden_macros = local_macro_names - allowed_macros
    if any(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", body) for name in forbidden_macros):
        return f"macro invocation forbidden in {function_name}() identity flow"
    patterns = CANONICAL_CONSUMER_PATTERNS.get(relative, ())
    if any(pattern.search(body) is None for pattern in patterns):
        return f"canonical identity flow missing from {function_name}()"
    return None


def generated_version_is_target(text: str) -> bool:
    """Require the generator's release version source to be the approved target."""
    return ("release_identity.json" in text and "ConvertFrom-Json" in text and
            re.search(r"(?m)^\s*\$FW_VERSION\s*=\s*"
                      r"\$IDENTITY\.firmware_version\s*$", text) is not None)


def c_define_is_target(text: str, name: str) -> bool:
    match = re.search(rf'(?m)^\s*#define\s+{re.escape(name)}\s+"([^"]+)"\s*$', text)
    return match is not None and match.group(1) == TARGET_VERSION


def c_define_is_counter(text: str) -> bool:
    match = re.search(r"(?m)^\s*#define\s+FW_VERSION_COUNTER\s+([0-9]+)(?:[uUlL]+)?\s*$", text)
    return match is not None and int(match.group(1)) == TARGET_VERSION_COUNTER


def valid_version_counter(value: object) -> bool:
    return type(value) is int and 0 < value <= 0xFFFFFFFF


def iter_release_files(root: Path, paths: tuple[str, ...] = DEFAULT_PATHS):
    """Yield existing text files under the configured release paths."""
    seen: set[Path] = set()
    for relative in paths:
        path = root / relative
        candidates = path.rglob("*") if path.is_dir() else (path,)
        for candidate in candidates:
            if not candidate.is_file() or candidate in seen:
                continue
            seen.add(candidate)
            yield candidate


def scan(root: Path, paths: tuple[str, ...] = DEFAULT_PATHS):
    """Return (file, line, token, text) tuples for forbidden matches."""
    findings = []
    contract_path = root / "release_identity.json"
    if contract_path.is_file():
        try:
            candidate_contract = json.loads(contract_path.read_text(encoding="utf-8"))
            revision = candidate_contract.get("firmware_revision")
            version_counter = candidate_contract.get("firmware_version_counter")
            internally_valid = (
                isinstance(revision, int) and 0 <= revision <= 999 and
                valid_version_counter(version_counter) and
                candidate_contract.get("firmware_version") ==
                candidate_contract.get("firmware_version_prefix", "") +
                f"{revision:03d}"
            )
            if candidate_contract != CONTRACT or not internally_valid:
                token = "<version-counter>" if not valid_version_counter(version_counter) else "<release-contract>"
                findings.append((contract_path, 0, token,
                                 "release identity differs from approved contract"))
        except (OSError, ValueError, TypeError) as exc:
            findings.append((contract_path, 0, "<release-contract>", str(exc)))
    elif (root / "gen_version.ps1").is_file():
        findings.append((contract_path, 0, "<release-contract>",
                         "release_identity.json is required"))
    patterns = [(token, re.compile(re.escape(token), re.IGNORECASE)) for token in FORBIDDEN]
    release_files = list(iter_release_files(root, paths))
    release_texts: dict[Path, str] = {}
    release_macro_names = set()
    release_macro_definitions: dict[str, list[str]] = {}
    for release_path in release_files:
        try:
            release_text = release_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        release_texts[release_path] = release_text
        release_macro_names.update(re.findall(
            rf"(?m)^\s*{PP_DIRECTIVE}\s*define\s+({C_IDENTIFIER})",
            strip_c_comments(release_text),
        ))
        if release_path.suffix.casefold() not in (".c", ".h", ".inc"):
            continue
        for name, replacement in re.findall(
                rf"(?m)^\s*{PP_DIRECTIVE}\s*define\s+({C_IDENTIFIER})(?:\([^\r\n)]*\))?[ \t]+([^\r\n]+?)\s*$",
                strip_c_comments(release_text)):
            release_macro_definitions.setdefault(name, []).append(replacement)
        for name in re.findall(rf"(?m)^\s*{PP_DIRECTIVE}\s*undef\s+({C_IDENTIFIER})",
                               strip_c_comments(release_text)):
            if name in CANONICAL_MACRO_DEFINITIONS:
                release_macro_definitions.setdefault(name, []).append("<undef>")
    for path in release_files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            findings.append((path, 0, "<read-error>", str(exc)))
            continue
        for number, line in enumerate(lines, 1):
            for token, pattern in patterns:
                if pattern.search(line):
                    findings.append((path, number, token, line.strip()))
        relative = path.relative_to(root).as_posix()
        expected_file_digest = CANONICAL_IDENTITY_FILE_SHA256.get(relative)
        if (expected_file_digest is not None and canonical_file_digest(
                release_texts.get(path, ""), relative) != expected_file_digest):
            findings.append((path, 0, "<identity-service>",
                             "noncanonical identity dependency; manual review required"))
        if relative in IDENTITY_CONSUMERS:
            for terminal_id in fixed_identity_findings("\n".join(lines)):
                if terminal_id not in IDENTITY_LITERAL_ALLOWLIST:
                    findings.append((path, 0, "<fixed-terminal-id>", terminal_id))
            required = IDENTITY_SERVICE_REQUIREMENTS.get(relative)
            if required is not None:
                function_name, service_pattern, output_symbol, allowed_uses = required
                body = c_function_body("\n".join(lines), function_name)
                if body is None or service_pattern.search(body) is None:
                    findings.append((path, 0, "<identity-service>",
                                     f"required call missing from {function_name}()"))
                else:
                    reason = canonical_identity_consumer("\n".join(lines), relative,
                                                         function_name, body,
                                                         release_macro_names,
                                                         release_macro_definitions)
                    if reason is not None:
                        findings.append((path, 0, "<identity-service>", reason))
                    elif output_symbol is not None:
                        residual = body
                        for allowed_use in allowed_uses:
                            residual = allowed_use.sub("", residual)
                        if re.search(rf"\b{re.escape(output_symbol)}\b", residual):
                            findings.append((path, 0, "<identity-service>",
                                             f"unapproved {output_symbol} data flow in {function_name}()"))
        if path.name.casefold() == "gen_version.ps1" and not generated_version_is_target("\n".join(lines)):
            findings.append((path, 0, "<target-version>", f"expected {TARGET_VERSION}"))
        if relative == "include/config.h" and not c_define_is_target("\n".join(lines), "FW_VERSION_STR"):
            findings.append((path, 0, "<target-version>", f"FW_VERSION_STR must be {TARGET_VERSION}"))
        if relative == "include/build_version.h" and not c_define_is_target("\n".join(lines), "FW_FULL_VERSION"):
            findings.append((path, 0, "<target-version>", f"FW_FULL_VERSION must be {TARGET_VERSION}"))
        if relative == "include/build_version.h" and not c_define_is_counter("\n".join(lines)):
            findings.append((path, 0, "<version-counter>",
                             f"FW_VERSION_COUNTER must be {TARGET_VERSION_COUNTER}UL"))
    return findings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--path", action="append", dest="paths", help="release path (repeatable)")
    args = parser.parse_args(argv)
    paths = tuple(args.paths) if args.paths else DEFAULT_PATHS
    findings = scan(args.root.resolve(), paths)
    if findings:
        for path, line, token, text in findings:
            print(f"release-guard: {path}:{line}: forbidden {token}: {text}", file=sys.stderr)
        print(f"release-guard: FAIL ({len(findings)} match(es))", file=sys.stderr)
        return 1
    print("release-guard: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
