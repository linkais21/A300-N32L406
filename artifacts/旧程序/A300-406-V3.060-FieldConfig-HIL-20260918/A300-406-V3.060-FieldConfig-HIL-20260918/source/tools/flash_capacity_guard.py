"""RES-01: App load-span gate and reproducible build evidence (standard library)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from map_ram_guard import FLASH_LIMITS, FLASH_ORIGINS, flash_used

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tools/flash_capacity_baseline.json"
WARNING_BYTES = 4096
CONFIG_FIELDS = ("compiler", "cflags", "asflags", "ldflags", "sdk_cflags",
                 "signature_cflags", "sources")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def configuration(data: dict) -> dict:
    value = data.get("configuration")
    if (not isinstance(value, dict) or set(value) != set(CONFIG_FIELDS)
            or any(not isinstance(v, str) for v in value.values())
            or any(not value[name].strip() for name in CONFIG_FIELDS if name != "sdk_cflags")):
        raise ValueError("invalid build configuration")
    return value


def config_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def record(args: argparse.Namespace) -> int:
    # This evidence does not replace BUILD-01 header/command dependencies.
    compiler = subprocess.run([str(args.compiler), "--version"], check=True,
                              capture_output=True, text=True, timeout=30).stdout.splitlines()[0]
    values = {name: getattr(args, name) for name in CONFIG_FIELDS if name != "compiler"}
    values["compiler"] = compiler
    for name, value in values.items():
        value = value.replace("\\", "/").replace(ROOT.as_posix(), "<repo>")
        value = re.sub(r"-Wl,-Map=\S+", "-Wl,-Map=<output.map>", value)
        values[name] = " ".join(value.split())
    write_json(args.output, {"schema_version": 1, "configuration": values,
                           "elf_sha256": digest(args.elf)})
    return 0


def check(args: argparse.Namespace) -> int:
    report = {"schema_version": 1, "status": "failed", "alerts": []}
    try:
        used = args.bin.stat().st_size
        span = flash_used(args.map.read_text(encoding="utf-8"))
        if used != span:
            raise ValueError(f"BIN/MAP span mismatch: BIN={used} MAP={span}")
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        if not isinstance(profile, dict) or not isinstance(baseline, dict):
            raise ValueError("invalid profile or baseline object")
        if profile.get("schema_version") != 1 or baseline.get("schema_version") != 1:
            raise ValueError("unsupported profile/baseline schema")
        current_config = configuration(profile)
        baseline_config = configuration(baseline)
        reference = baseline.get("used_bytes")
        if (type(reference) is not int or not 8 <= reference <= FLASH_LIMITS["app"]
                or baseline.get("origin") != FLASH_ORIGINS["app"]
                or baseline.get("limit_bytes") != FLASH_LIMITS["app"]):
            raise ValueError("invalid baseline capacity")
        elf_hash = digest(args.elf)
        if profile.get("elf_sha256") != elf_hash:
            raise ValueError("ELF does not match recorded build profile; rebuild with -B")
        remaining = FLASH_LIMITS["app"] - used
        comparable = current_config == baseline_config
        if remaining < WARNING_BYTES:
            report["alerts"].append("LOW_HEADROOM")
        if not comparable:
            report["alerts"].append("CONFIGURATION_CHANGED")
        report.update(origin=FLASH_ORIGINS["app"], limit_bytes=FLASH_LIMITS["app"],
                      used_bytes=used, map_span_bytes=span, remaining_bytes=remaining,
                      warning_bytes=WARNING_BYTES, baseline_used_bytes=reference,
                      delta_bytes=used-reference, baseline_comparable=comparable,
                      configuration=current_config, configuration_sha256=config_hash(current_config),
                      bin_sha256=digest(args.bin), elf_sha256=elf_hash,
                      map_sha256=digest(args.map))
        if remaining < 0:
            raise ValueError("App exceeds frozen Flash capacity")
        report["status"] = "passed"
    except (OSError, UnicodeError, ValueError) as exc:
        report["error"] = str(exc)
    # Replace an earlier success report even when today's inputs are invalid.
    write_json(args.output, report)
    if report["status"] != "passed":
        print(f"Flash guard FAIL: {report['error']}")
        return 1
    print(f"Flash guard PASS: used={used}/{FLASH_LIMITS['app']} remaining={remaining} "
          f"delta={used-reference:+d} baseline_comparable={comparable}")
    for alert in report["alerts"]:
        # Advisories are distinct from compiler 'warning:' diagnostics, which
        # the release builder rejects. Preserve these in stdout and JSON.
        print(f"Flash guard ALERT {alert}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    recorder = commands.add_parser("record")
    recorder.add_argument("--compiler", type=Path, required=True)
    recorder.add_argument("--elf", type=Path, required=True)
    recorder.add_argument("--output", type=Path, required=True)
    for name in CONFIG_FIELDS:
        if name != "compiler":
            recorder.add_argument("--" + name.replace("_", "-"), required=True)
    checker = commands.add_parser("check")
    for name in ("bin", "map", "elf", "profile", "output"):
        checker.add_argument("--" + name, type=Path, required=True)
    checker.add_argument("--baseline", type=Path, default=BASELINE)
    args = parser.parse_args()
    try:
        return record(args) if args.command == "record" else check(args)
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Flash guard FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
