#!/usr/bin/env python3
"""Reject legacy product/version identifiers in release-controlled files."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FORBIDDEN = ("T663B", "A300_202511", "V1.274")
TARGET_VERSION = "T360-A300_406_20260823000000,V3.000"
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
)

IDENTITY_CONSUMERS = (
    "src/main.c", "src/jt808.c", "src/jt808_params.c", "src/terminal_identity.c",
    "src/f39_reply.c",
)
SEVEN_BYTE_LITERAL = re.compile(r'"([A-Za-z0-9]{7})"')
STRING_LITERAL = re.compile(r'"([A-Za-z0-9]*)"')
CHAR_LITERAL = re.compile(r"^(?:L|u|U)?'((?:\\.|[^\\'])+)'$")
INTEGER_LITERAL = re.compile(
    r"^(0[xX][0-9A-Fa-f]+|0[0-7]*|[1-9][0-9]*)(?:[uU](?:[lL]{1,2})?|[lL]{1,2}[uU]?)?$"
)
IDENTITY_LITERAL_ALLOWLIST = {"DUALSET", "invalid"}
IDENTITY_SERVICE_REQUIREMENTS = {
    "src/main.c": ("main", re.compile(
        r"\bs_terminal\.terminal_id\s*\[\s*0\s*\]\s*=\s*'\\0'\s*;"
    ), None, ()),
    "src/jt808.c": ("refresh_terminal_identity", re.compile(
        r"terminal_identity_load\s*\(\s*terminal_id\s*\)"
    ), "terminal_id", (
        re.compile(r"char\s+terminal_id\s*\[\s*8\s*\]\s*;"),
        re.compile(r"terminal_identity_load\s*\(\s*terminal_id\s*\)"),
        re.compile(r"memcpy\s*\(\s*s_term\.terminal_id\s*,\s*terminal_id\s*,"
                   r"\s*sizeof\s*\(\s*s_term\.terminal_id\s*\)\s*\)"),
    )),
    "src/jt808_params.c": ("jt808_params_handle_info_query", re.compile(
        r"terminal_identity_load\s*\(\s*tid\s*\)"
    ), "tid", (
        re.compile(r"char\s+tid\s*\[\s*8\s*\]\s*;"),
        re.compile(r"terminal_identity_load\s*\(\s*tid\s*\)"),
        re.compile(r"memcpy\s*\(\s*body\s*\+\s*pos\s*,\s*tid\s*,\s*7\s*\)"),
    )),
    "src/terminal_identity.c": ("terminal_identity_load", re.compile(
        r"return\s+terminal_id_derive\s*\(\s*config->pid\s*,\s*imei\s*,\s*out\s*\)\s*;"
    ), "out", (
        re.compile(r"out\s*==\s*NULL"),
        re.compile(r"out\s*\[\s*0\s*\]\s*=\s*'\\0'"),
        re.compile(r"return\s+terminal_id_derive\s*\(\s*config->pid\s*,\s*imei\s*,\s*out\s*\)\s*;"),
    )),
    "src/f39_reply.c": ("device_id", re.compile(
        r"return\s+terminal_id_derive\s*\(\s*c->pid\s*,\s*imei\s*,\s*terminal_id\s*\)\s*;"
    ), "terminal_id", (
        re.compile(r"return\s+terminal_id_derive\s*\(\s*c->pid\s*,\s*imei\s*,\s*terminal_id\s*\)\s*;"),
    )),
}


def strip_c_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\r\n]*", "", text, flags=re.DOTALL)


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


def c_object_aliases(text: str, symbol: str) -> set[str]:
    """Return object-like macro names that expand directly to symbol/aliases."""
    clean = strip_c_comments(text)
    aliases = {symbol}
    raw_definitions = re.findall(
        r"(?m)^\s*#\s*define\s+([A-Za-z_]\w*)(?:\([^\r\n)]*\))?[ \t]+([^\r\n]+?)\s*$",
        clean,
    )
    definitions = []
    for name, replacement in raw_definitions:
        identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", replacement))
        definitions.append((name, identifiers))
    changed = True
    while changed:
        changed = False
        for name, targets in definitions:
            if targets & aliases and name not in aliases:
                aliases.add(name)
                changed = True
    aliases.remove(symbol)
    return aliases


def generated_version_is_target(text: str) -> bool:
    """Require the generator's release version source to be the approved target."""
    match = re.search(r'(?m)^\s*\$FW_VERSION\s*=\s*"([^"]+)"\s*$', text)
    return match is not None and match.group(1) == TARGET_VERSION


def c_define_is_target(text: str, name: str) -> bool:
    match = re.search(rf'(?m)^\s*#define\s+{re.escape(name)}\s+"([^"]+)"\s*$', text)
    return match is not None and match.group(1) == TARGET_VERSION


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
    patterns = [(token, re.compile(re.escape(token), re.IGNORECASE)) for token in FORBIDDEN]
    for path in iter_release_files(root, paths):
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
                elif output_symbol is not None:
                    residual = body
                    for allowed_use in allowed_uses:
                        residual = allowed_use.sub("", residual)
                    if re.search(rf"\b{re.escape(output_symbol)}\b", residual):
                        findings.append((path, 0, "<identity-service>",
                                         f"unapproved {output_symbol} data flow in {function_name}()"))
                    else:
                        aliases = c_object_aliases("\n".join(lines), output_symbol)
                        if any(re.search(rf"\b{re.escape(alias)}\b", residual) for alias in aliases):
                            findings.append((path, 0, "<identity-service>",
                                             f"unapproved alias data flow in {function_name}()"))
        if path.name.casefold() == "gen_version.ps1" and not generated_version_is_target("\n".join(lines)):
            findings.append((path, 0, "<target-version>", f"expected {TARGET_VERSION}"))
        if relative == "include/config.h" and not c_define_is_target("\n".join(lines), "FW_VERSION_STR"):
            findings.append((path, 0, "<target-version>", f"FW_VERSION_STR must be {TARGET_VERSION}"))
        if relative == "include/build_version.h" and not c_define_is_target("\n".join(lines), "FW_FULL_VERSION"):
            findings.append((path, 0, "<target-version>", f"FW_FULL_VERSION must be {TARGET_VERSION}"))
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
