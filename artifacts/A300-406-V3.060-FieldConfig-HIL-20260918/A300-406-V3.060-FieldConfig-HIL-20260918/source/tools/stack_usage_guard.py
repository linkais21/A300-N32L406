#!/usr/bin/env python3
"""RAM-01: final-link evidence. Known frame sums are not whole-program bounds."""

from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def load(paths: list[Path]) -> dict[str, int]:
    usage: dict[str, int] = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            fields = line.split("\t")
            if (len(fields) != 3 or not fields[1].isdigit()
                    or fields[2] != "static" or ":" not in fields[0]):
                raise ValueError(f"invalid/unbounded stack evidence: {path.name}: {line}")
            name = fields[0].rsplit(":", 1)[-1]
            usage[name] = max(usage.get(name, 0), int(fields[1]))
    if not usage:
        raise ValueError("empty stack evidence")
    return usage


def record(elf: Path, map_path: Path, reports: list[Path], output: Path) -> None:
    if not reports or not any(".ltrans" in p.name for p in reports):
        raise ValueError("missing final LTO stack report; rebuild with -B")
    load(reports)
    write_json(output, {"schema_version": 1, "elf_sha256": digest(elf),
                        "map_sha256": digest(map_path),
                        "reports": [{"path": p.resolve().relative_to(output.parent.resolve()).as_posix(),
                                     "sha256": digest(p)} for p in reports]})


def verify_evidence(elf: Path, map_path: Path, manifest: Path) -> list[Path]:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if (data.get("schema_version") != 1 or data.get("elf_sha256") != digest(elf)
            or data.get("map_sha256") != digest(map_path)):
        raise ValueError("stale ELF/MAP stack evidence; rebuild with -B")
    reports = []
    for item in data.get("reports", []):
        path = (manifest.parent / item["path"]).resolve()
        if not path.is_relative_to(manifest.parent.resolve()) or digest(path) != item["sha256"]:
            raise ValueError("stale stack report; rebuild with -B")
        reports.append(path)
    if not any(".ltrans" in path.name for path in reports):
        raise ValueError("missing final LTO stack evidence")
    return reports


def analyze(disassembly: str, frames: dict[str, int]) -> dict:
    graph: dict[str, set[str]] = {}
    indirect, tails = [], []
    caller = None
    for line in disassembly.splitlines():
        header = re.match(r"^[0-9a-fA-F]+ <(.+)>:$", line.strip())
        if header:
            caller = header[1]
            graph.setdefault(caller, set())
            continue
        instruction = re.match(r"^\s*[0-9a-fA-F]+:\s+(?:[0-9a-fA-F]{2,8}\s+)+([a-z][a-z0-9.]*)\s*(.*)", line)
        if not caller or not instruction:
            continue
        op, operands = instruction.groups()
        target = re.search(r"<([^>]+)>", operands)
        if op in ("bl", "bl.w", "blx"):
            if target:
                graph[caller].add(target[1])
            else:
                indirect.append({"caller": caller, "instruction": line.strip()})
        elif re.fullmatch(r"b(?:eq|ne|cs|cc|mi|pl|vs|vc|hi|ls|ge|lt|gt|le)?(?:\.w|\.n)?", op) and target:
            if target[1].split("+0x")[0] != caller:
                tails.append({"caller": caller, "target": target[1]})
        elif ((op == "bx" and operands.strip() != "lr")
              or (op.startswith(("ldr", "mov")) and re.match(r"pc\s*,", operands))):
            indirect.append({"caller": caller, "instruction": line.strip()})
    # GCC 14 .su omits the numerical id on constprop/isra clones (but retains
    # the clone kind). Duplicate .su names already use their maximum frame.
    # Never borrow an unoptimized original function's frame for a clone.
    resolved = {}
    names = set(graph) | {n for targets in graph.values() for n in targets}
    for name in names:
        source = re.sub(r"\.lto_priv\.\d+$", "", name)
        source = re.sub(r"\.(constprop|isra)\.\d+", r".\1", source)
        if name in frames or source in frames:
            resolved[name] = frames[name] if name in frames else frames[source]
    missing = sorted(names - resolved.keys())
    cycles, memo = set(), {}

    def walk(name, active):
        if name in active:
            cycles.add(" -> ".join((*active, name)))
            return 0, []
        if name in memo:
            return memo[name]
        best, path = 0, []
        for target in sorted(graph.get(name, ())):
            size, candidate = walk(target, (*active, name))
            if size > best:
                best, path = size, candidate
        result = (resolved.get(name, 0) + best, [name] + path)
        memo[name] = result
        return result

    roots = {}
    for name in sorted(graph):
        size, path = walk(name, ())
        roots[name] = {"known_frame_sum": size, "path": path}
    return {"roots": roots, "frames": resolved,
            "direct_edges": {k: sorted(v) for k, v in sorted(graph.items())},
            "missing_frames": missing, "indirect_transfers": indirect,
            "tail_transfers": tails, "cycles": sorted(cycles),
            "complete": bool(graph) and not (missing or indirect or tails or cycles)}


def check(elf: Path, map_path: Path, manifest: Path, objdump: Path, output: Path,
          report_only: bool = False) -> int:
    report = {"schema_version": 1, "status": "failed"}
    try:
        frames = load(verify_evidence(elf, map_path, manifest))
        disassembly = subprocess.run([str(objdump), "-d", str(elf)], check=True,
                                     capture_output=True, text=True, timeout=60).stdout
        output.with_suffix(".disassembly.txt").write_text(disassembly, encoding="utf-8")
        analysis = analyze(disassembly, frames)
        if "main" not in analysis["frames"]:
            raise ValueError("missing final main stack frame")
        report.update(analysis)
        report.update(elf_sha256=digest(elf), map_sha256=digest(map_path),
                      evidence_sha256=digest(manifest),
                      known_main_frame_sum=analysis["roots"]["main"]["known_frame_sum"],
                      status="incomplete",
                      runtime_gaps=["heap peak/hard bound is unverified (RAM-02)",
                                    "IRQ nesting, hardware/FPU/alignment and fault frames are unverified",
                                    "cold-start and stress HIL stack watermarks are unverified"],
                      error="no proven whole-program stack/heap/exception bound")
        main_path = analysis["roots"]["main"]
        print(f"stack-guard: known main call-frame sum={main_path['known_frame_sum']} B: "
              + " -> ".join(main_path["path"]))
        print(f"stack-guard: missing frames={len(analysis['missing_frames'])}, "
              f"indirect transfers={len(analysis['indirect_transfers'])}, "
              f"tail transfers={len(analysis['tail_transfers'])}, cycles={len(analysis['cycles'])}")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as exc:
        report["error"] = str(exc)
    write_json(output, report)
    print(f"stack-guard: {report['status'].upper()}: {report['error']}")
    return 0 if report_only and report["status"] == "incomplete" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("record", "check"):
        command = commands.add_parser(name)
        command.add_argument("--elf", type=Path, required=True)
        command.add_argument("--map", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        if name == "record":
            command.add_argument("--reports", type=Path, nargs="+", required=True)
        else:
            command.add_argument("--manifest", type=Path, required=True)
            command.add_argument("--objdump", type=Path, required=True)
            command.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    if args.command == "check":
        return check(args.elf, args.map, args.manifest, args.objdump, args.output, args.report_only)
    try:
        record(args.elf, args.map, args.reports, args.output)
    except (OSError, ValueError) as exc:
        print(f"stack-guard: FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
