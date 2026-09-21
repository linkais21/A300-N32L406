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


def table_target_evidence(disassembly: str) -> list[dict]:
    """Decode locally guarded PC tables; never assert guard dominance.

    Input is objdump -d from the same ELF as the stack report. Data directives
    are little endian; Thumb's table base is instruction address + 4, including
    at halfword alignment. Unknown layouts stay unresolved. Even a decoded
    table can be entered without its local compare (including via a callback).
    """
    rows, owner = [], None
    for line in disassembly.splitlines():
        header = re.match(r"^[0-9a-fA-F]+ <(.+)>:$", line.strip())
        if header:
            owner = header[1]
        match = re.match(r"^\s*([0-9a-fA-F]+):\s+((?:(?:[0-9a-fA-F]{2}){1,4}\s+)+)"
                         r"([.a-z][a-z0-9.]*)\s*(.*)", line)
        if match and owner:
            address, raw, op, operands = match.groups()
            words = raw.split()
            rows.append({"address": int(address, 16), "size": sum(len(w) // 2 for w in words),
                         "raw": words, "op": op, "operands": operands.split("@")[0].strip(),
                         "owner": owner})
    code = {r["address"]: r for r in rows if not r["op"].startswith(".")}
    data = {}
    for row in rows:
        width = {".byte": 1, ".short": 2, ".word": 4}.get(row["op"])
        if width and len(row["raw"]) == 1 and row["size"] == width:
            blob = int(row["raw"][0], 16).to_bytes(width, "little")
            data.update({row["address"] + i: byte for i, byte in enumerate(blob)})
    evidence = []
    for i, row in enumerate(rows):
        if row["op"] not in ("tbb", "tbh"):
            continue
        item = {"caller": row["owner"], "address": row["address"], "kind": row["op"],
                "status": "unresolved", "reason": "unsupported local bounds/table layout"}
        evidence.append(item)
        halfword = row["op"] == "tbh"
        operand = re.fullmatch(r"\[pc, (r\d+|sl|fp|ip)" +
                              (r", lsl #1\]" if halfword else r"\]"), row["operands"])
        if not operand or i < 2 or row["size"] != 4:
            continue
        compare, branch = rows[i-2:i]
        bound = re.fullmatch(r"(r\d+|sl|fp|ip), #(0x[0-9a-fA-F]+|\d+)", compare["operands"])
        if (compare["op"] not in ("cmp", "cmp.w") or not bound
                or bound[1] != operand[1] or not re.fullmatch(r"bhi(?:\.n|\.w)?", branch["op"])
                or compare["owner"] != row["owner"] or branch["owner"] != row["owner"]
                or compare["address"] + compare["size"] != branch["address"]
                or branch["address"] + branch["size"] != row["address"]):
            continue
        maximum = int(bound[2], 16 if bound[2].startswith("0x") else 10)
        # Bounded audit work, not an architectural table-size assumption.
        if maximum > 4095:
            item["reason"] = "table exceeds audit entry limit (4096)"
            continue
        width, base = (2 if halfword else 1), row["address"] + 4
        end = base + (maximum + 1) * width
        default = re.match(r"([0-9a-fA-F]+)\s+<", branch["operands"])
        if not default or int(default[1], 16) not in code:
            item["reason"] = "range-check destination is not an instruction boundary"
            continue
        if any(address not in data for address in range(base, end)):
            item["reason"] = "missing table data bytes"
            continue
        blob = bytes(data[address] for address in range(base, end))
        targets = []
        for index in range(maximum + 1):
            offset = int.from_bytes(blob[index*width:(index+1)*width], "little")
            target = base + 2 * offset
            if target not in code or base <= target < end:
                item["reason"] = "table target is not a code instruction boundary"
                break
            targets.append({"index": index, "offset": offset, "address": target,
                            "function": code[target]["owner"]})
        else:
            bypass = []
            for source in rows:
                # Annotated branch/call operands only; literal loads are not entries.
                if not (re.fullmatch(r"b(?:l|lx|eq|ne|cs|cc|mi|pl|vs|vc|hi|ls|ge|lt|gt|le)?(?:\.w|\.n)?", source["op"])
                        or source["op"] in ("cbz", "cbnz")):
                    continue
                dest = re.search(r"\b([0-9a-fA-F]+)\s+<", source["operands"])
                if dest and compare["address"] < int(dest[1], 16) <= row["address"]:
                    bypass.append(source["address"])
            item.pop("reason")
            item.update(status="decoded_local_guard", compare_address=compare["address"],
                        default_address=int(default[1], 16), maximum_index=maximum,
                        table_address=base, table_hex=blob.hex(), targets=targets,
                        bypass_entries=bypass,
                        unresolved_obligations=[
                            "prove all incoming paths execute the compare and unsigned guard",
                            "exclude unknown indirect entries and out-of-range indices",
                            "prove stack state at each target, including interior entries"])
    return evidence


def machine_frame_evidence(disassembly: str) -> dict[str, dict]:
    """Prove a small Thumb-1 straight-line subset from encodings, not mnemonics.

    Entry SP and ordinary ABI LR are assumed. Exception entry/nesting is NOT
    included. No calls, branches, stores, IT, SP writes or unknown encodings
    are accepted. Loads can fault: fault frames remain a runtime obligation.
    Only the contiguous entry-to-BX-LR prefix is reachable in this subset;
    following literal pools/padding are not executed. Interior-entry tails
    remain unresolved by the caller analysis.
    """
    evidence = {}
    blocks = re.finditer(r"^([0-9a-fA-F]+) <([^>]+)>:\s*\n(.*?)(?=^[0-9a-fA-F]+ <|\Z)",
                         disassembly, re.M | re.S)
    for match in blocks:
        start, name, body = match.groups()
        if name.endswith(("_Handler", "_IRQHandler")):
            continue
        address = int(start, 16)
        if address & 1:
            continue
        registers = [None] * 16
        registers[14] = "entry_lr"
        stack, blob, peak = [], bytearray(), 0
        for line in body.splitlines():
            if not line.strip():
                continue
            row = re.fullmatch(r"\s*([0-9a-fA-F]+):\s+([0-9a-fA-F]{4})\s+"
                               r"([a-z][a-z0-9.]*)\s*(.*)", line)
            if not row or int(row[1], 16) != address:
                break
            word = int(row[2], 16)
            blob.extend(word.to_bytes(2, "little"))
            address += 2
            if word == 0x4770:  # BX LR; no conditional execution accepted.
                if not stack and registers[14] == "entry_lr":
                    evidence[name] = dict(frame_bytes=peak, address=int(start, 16),
                                          end_address=address, code_hex=blob.hex(),
                                          proof="thumb1_straight_line_balanced_return")
                break
            if word == 0xbf00:  # NOP, not IT/hints.
                continue
            if word & 0xfe00 == 0xb400:  # PUSH low registers and optional LR.
                regs = [r for r in range(8) if word & (1 << r)]
                if word & 0x100:
                    regs.append(14)
                if not regs:
                    break
                stack[0:0] = [registers[r] for r in regs]
                peak = max(peak, 4 * len(stack))
            elif word & 0xff00 == 0xbc00:  # POP low regs only; never POP PC.
                regs = [r for r in range(8) if word & (1 << r)]
                if not regs or len(stack) < len(regs):
                    break
                for reg in regs:
                    registers[reg] = stack.pop(0)
            elif word & 0xff00 == 0x4600:  # MOV register (not ADD/BX).
                dest = (word & 7) | ((word >> 4) & 8)
                source = (word >> 3) & 15
                if dest in (13, 15) or source in (13, 15):
                    break
                registers[dest] = registers[source]
            elif word & 0xf800 in (0x2000, 0x4800):  # MOVS imm / LDR literal.
                registers[(word >> 8) & 7] = None
            elif word & 0xf800 == 0x6800:  # LDR immediate, low regs only.
                registers[word & 7] = None
            else:
                break
    return evidence


def analyze(disassembly: str, frames: dict[str, int]) -> dict:
    graph: dict[str, set[str]] = {}
    indirect, tails, internal_calls = [], [], []
    condition = r"(?:eq|ne|cs|hs|cc|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le|al)?"
    width = r"(?:\.w|\.n)?"
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
        # Match the instruction class first: BLE is B.LE, not a BL call.
        # Conditional calls in IT blocks retain their taken execution path.
        if re.fullmatch(r"blx?" + condition + width, op):
            if target:
                graph[caller].add(target[1])
                if "+0x" in target[1]:
                    internal_calls.append({"caller": caller, "target": target[1],
                                           "instruction": line.strip()})
            else:
                indirect.append({"caller": caller, "instruction": line.strip(),
                                 "kind": "register_call"})
        elif (re.fullmatch(r"b" + condition + width, op)
              or op in ("cbz", "cbnz")) and target:
            if target[1].split("+0x")[0] != caller:
                tails.append({"caller": caller, "target": target[1]})
        elif op in ("tbb", "tbh"):
            # Table entries are data, not annotated branch operands. Until
            # their bounds/targets are proven, even a local switch is unknown.
            indirect.append({"caller": caller, "instruction": line.strip(),
                             "kind": "table_branch"})
        elif ((re.fullmatch(r"bx" + condition + width, op) and operands.strip() != "lr")
              or (op.startswith(("ldr", "mov")) and re.match(r"pc\s*,", operands))):
            indirect.append({"caller": caller, "instruction": line.strip(),
                             "kind": "register_branch" if op.startswith("bx") else "pc_write"})
    direct_edges = {k: sorted(v) for k, v in sorted(graph.items())}
    # An internal BL entry is not covered by the owner's prologue/frame proof.
    # Follow its owner for diagnostic reachability, retaining an explicit gap.
    # A local subroutine is not necessarily recursion through the full entry.
    for transfer in internal_calls:
        caller, target = transfer["caller"], transfer["target"]
        owner = target.split("+0x")[0]
        graph[caller].discard(target)
        if owner != caller:
            graph[caller].add(owner)
    tables = table_target_evidence(disassembly)
    for table in tables:
        for target in table.get("targets", []):
            if target["function"] != table["caller"]:
                # Candidate edges only ADD reachability. The table remains an
                # unresolved transfer; no frame-release or completeness credit.
                graph[table["caller"]].add(target["function"])
    # Include tail successors without assuming the caller has released its
    # frame. Sum both frames conservatively; keep every tail as an unresolved
    # transfer. Interior entries follow the owning symbol's successors, but
    # are NOT proof that its prologue/stack state matches the entry point.
    for transfer in tails:
        target = transfer["target"].split("+0x")[0]
        graph[transfer["caller"]].add(target)
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
    machine_frames = machine_frame_evidence(disassembly)
    for name in names - resolved.keys():
        if name in machine_frames:
            resolved[name] = machine_frames[name]["frame_bytes"]
    missing = sorted(names - resolved.keys())
    cycles, memo, cycle_nodes = set(), {}, set()

    def walk(name, active):
        if name in active:
            cycles.add(" -> ".join((*active, name)))
            cycle_nodes.update(active[active.index(name):])
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
    # Reachability includes direct/tail transfers and decoded table candidates. An unresolved
    # indirect call may reach additional functions; never call these lists
    # an exhaustive runtime bound. Cyclic frame sums are diagnostic only.
    root_gaps = {}
    for root in sorted(graph):
        if root != "main" and not root.endswith("_Handler") and not root.endswith("_IRQHandler"):
            continue
        reachable, pending = set(), [root]
        while pending:
            name = pending.pop()
            if name not in reachable:
                reachable.add(name)
                pending.extend(graph.get(name, ()))
        root_gaps[root] = {
            "reachable_functions": sorted(reachable),
            "missing_frames": sorted(reachable - resolved.keys()),
            "indirect_transfers": [t for t in indirect if t["caller"] in reachable],
            "tail_transfers": [t for t in tails if t["caller"] in reachable],
            "internal_calls": [t for t in internal_calls if t["caller"] in reachable],
            "cycle_reachable": bool(reachable & cycle_nodes),
        }
    return {"roots": roots, "frames": resolved,
            "machine_frame_evidence": machine_frames,
            "direct_edges": direct_edges,
            "call_edges": {k: sorted(v) for k, v in sorted(graph.items())},
            "root_gaps": root_gaps,
            "frame_sum_policy": "sum known direct/tail/table-candidate frames without tail-release credit; "
                                "internal calls follow owners with unproven entry state; "
                                "unknown frames omitted; cycles unbounded",
            "missing_frames": missing, "indirect_transfers": indirect,
            "internal_calls": internal_calls,
            "table_target_evidence": tables,
            "tail_transfers": tails, "cycles": sorted(cycles),
            "complete": bool(graph) and not (missing or indirect or tails or internal_calls or cycles)}


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
              f"tail transfers={len(analysis['tail_transfers'])}, "
              f"internal calls={len(analysis['internal_calls'])}, cycles={len(analysis['cycles'])}")
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
