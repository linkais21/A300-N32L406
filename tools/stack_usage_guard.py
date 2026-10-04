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


def reviewed_nano_printf_targets(elf_path: Path) -> dict[int, dict]:
    """Bind the audited newlib-nano callback and switch to exact linked code."""
    from elftools.elf.elffile import ELFFile

    # ARM GNU 14.3.1 nano-vfprintf: _svfiprintf_r loads the Thumb address of
    # __ssputs_r at +0x1e8 and passes it to its sole _printf_i call. _printf_i
    # forwards that register to _printf_common. Its 22-entry switch is guarded
    # by an unsigned <=21 comparison and every entry remains in _printf_i.
    reviewed = {
        "_svfiprintf_r": (496, "d4c64c12ab49802fa37b431fd61f6787c554f2d0de715976a69ebfc060e16919"),
        "_printf_i": (588, "35d78d43f25c23485670292b24b48cd3f874318f4f118d0bd5cc08ae50f79f4d"),
        "_printf_common": (218, "5c0333e23c9729600ccd9be755c0485536ab2df6ba21b32a82ce5ee01249093b"),
    }
    with elf_path.open("rb") as stream:
        elf = ELFFile(stream)
        symbols = elf.get_section_by_name(".symtab")
        section = elf.get_section_by_name(".text")
        if symbols is None or section is None:
            return {}
        names = {name: [item for item in symbols.iter_symbols() if item.name == name]
                 for name in (*reviewed, "__ssputs_r")}
        if any(len(items) != 1 for items in names.values()):
            return {}
        code = {}
        starts = {}
        for name, (size, expected) in reviewed.items():
            symbol = names[name][0]
            start = symbol["st_value"] & ~1
            offset = start - section["sh_addr"]
            if symbol["st_size"] != size or offset < 0:
                return {}
            blob = section.data()[offset:offset + size]
            if len(blob) != size or hashlib.sha256(blob).hexdigest() != expected:
                return {}
            code[name], starts[name] = blob, start
        writer = names["__ssputs_r"][0]
        if (int.from_bytes(code["_svfiprintf_r"][0x1e8:0x1ec], "little")
                != writer["st_value"]):
            return {}
        table = code["_printf_i"][0x44:0x9c]
        offsets = {(int.from_bytes(table[i:i + 4], "little") & ~1) - starts["_printf_i"]
                   for i in range(0, len(table), 4)}
        if len(table) != 22 * 4 or offsets != {
                0x2a, 0x9c, 0xb0, 0xda, 0x16a, 0x172, 0x1b8, 0x1da}:
            return {}
        sites = {"_printf_common": (0x60, 0x9e, 0xd0),
                 "_printf_i": (0x3e, 0x206, 0x226)}
        return {starts[name] + offset: {
            "caller": name, "target": None if (name, offset) == ("_printf_i", 0x3e)
            else "__ssputs_r", "proof": "reviewed_nano_printf_code_sha256",
            "code_sha256": reviewed[name][1], "elf_sha256": digest(elf_path)}
            for name, offsets in sites.items() for offset in offsets}


def reviewed_dmul_internal_call(elf_path: Path) -> dict[int, dict]:
    """Bound the reviewed libgcc helper within its existing 16-byte frame."""
    from elftools.elf.elffile import ELFFile

    with elf_path.open("rb") as stream:
        elf = ELFFile(stream)
        symbols = elf.get_section_by_name(".symtab")
        section = elf.get_section_by_name(".text")
        if symbols is None or section is None:
            return {}
        matches = [item for item in symbols.iter_symbols() if item.name == "__aeabi_dmul"]
        if len(matches) != 1 or matches[0]["st_size"] != 596:
            return {}
        start = matches[0]["st_value"] & ~1
        offset = start - section["sh_addr"]
        if offset < 0:
            return {}
        blob = section.data()[offset:offset + 596]
        # The sole interior BL enters +0x1dc. From that entry the reviewed
        # helper has no SP write; it returns by BX LR or the caller's POP PC.
        expected = "214003e199bc3ae6b1ab390050449fd72f3db2118cdc5106bd8a2dbf48c8ad1f"
        if (len(blob) != 596 or hashlib.sha256(blob).hexdigest() != expected or
                blob[0x1c:0x20] != bytes.fromhex("00f0def8")):
            return {}
        return {start + 0x1c: {"caller": "__aeabi_dmul",
                               "target": "__aeabi_dmul+0x1dc",
                               "frame_bytes": 16,
                               "proof": "reviewed_libgcc_code_sha256",
                               "code_sha256": expected, "elf_sha256": digest(elf_path)}}


def reviewed_startup_evidence(elf_path: Path) -> dict:
    """Bind startup labels, the default IRQ, and constructor calls to ELF data."""
    from elftools.elf.elffile import ELFFile

    reviewed = {
        "Reset_Handler": (52, "035e0975848a6f1191b20074c8885c205a2d1ab58fc72fe209aa877d60787b90"),
        "ADC_IRQHandler": (2, "575fc8fa9e92ffe7d57a6aef6f1168f39da04f07d6bcd5b5e17883bff7b33165"),
        "__libc_init_array": (72, "cfb531f04870922d1408b2ea7bebde176fc38df8b4ed9240dde330e3f77a2a5d"),
        "frame_dummy": (36, "64f1a264e15c340add93e4e359bb9148541c33c8d414d354eef94efa6abaadf3"),
        "register_tm_clones": (36, "fed0b3c07108990514f33afe004f478eb29c14257e7ef9bcd6f65d6e7ca5e05c"),
    }
    labels = {"CopyDataInit": 0x04, "LoopCopyDataInit": 0x0c,
              "FillZerobss": 0x1a, "LoopFillZerobss": 0x20}
    relocation_spans = {"Reset_Handler": ((38, 50),),
                        "__libc_init_array": ((16, 20), (56, 72)),
                        "frame_dummy": ((28, 36),)}

    def branch_target(blob: bytes, offset: int, start: int) -> int | None:
        first = int.from_bytes(blob[offset:offset + 2], "little")
        second = int.from_bytes(blob[offset + 2:offset + 4], "little")
        if (first & 0xf800) != 0xf000 or (second & 0xd000) != 0xd000:
            return None
        sign = (first >> 10) & 1
        first_high = (~((second >> 13) ^ sign)) & 1
        second_high = (~((second >> 11) ^ sign)) & 1
        displacement = (sign << 24) | (first_high << 23) | (second_high << 22)
        displacement |= (first & 0x3ff) << 12 | (second & 0x7ff) << 1
        if sign:
            displacement -= 1 << 25
        return start + offset + 4 + displacement

    with elf_path.open("rb") as stream:
        elf = ELFFile(stream)
        symbols = elf.get_section_by_name(".symtab")
        code = elf.get_section_by_name(".text")
        vectors = elf.get_section_by_name(".isr_vector")
        constructors = elf.get_section_by_name(".init_array")
        preinit = elf.get_section_by_name(".preinit_array")
        if not all((symbols, code, vectors, constructors)) or (preinit and preinit.data()):
            return {}
        required_names = (*reviewed, *labels, "Default_Handler", "SystemInit", "main",
                          "_init", "__preinit_array_start", "__preinit_array_end",
                          "__init_array_start", "__init_array_end", "object.0",
                          "__EH_FRAME_BEGIN__")
        names = {name: [item for item in symbols.iter_symbols() if item.name == name]
                 for name in required_names}
        if any(len(items) != 1 for items in names.values()):
            return {}
        starts = {}
        blobs = {}
        for name, (size, expected) in reviewed.items():
            symbol = names[name][0]
            start = symbol["st_value"] & ~1
            offset = start - code["sh_addr"]
            blob = code.data()[offset:offset + size] if offset >= 0 else b""
            normalized = bytearray(blob)
            for first, last in relocation_spans.get(name, ()):
                normalized[first:last] = bytes(last - first)
            if len(blob) != size or hashlib.sha256(normalized).hexdigest() != expected:
                return {}
            starts[name] = start
            blobs[name] = blob
        for offset, target in ((38, "SystemInit"), (42, "__libc_init_array"),
                               (46, "main")):
            if branch_target(blobs["Reset_Handler"], offset, starts["Reset_Handler"]) != (
                    names[target][0]["st_value"] & ~1):
                return {}
        if branch_target(blobs["__libc_init_array"], 16,
                         starts["__libc_init_array"]) != (names["_init"][0]["st_value"] & ~1):
            return {}
        array_words = [int.from_bytes(blobs["__libc_init_array"][offset:offset + 4], "little")
                       for offset in (56, 60, 64, 68)]
        if array_words != [names[name][0]["st_value"] for name in (
                "__preinit_array_end", "__preinit_array_start",
                "__init_array_start", "__init_array_end")]:
            return {}
        if [int.from_bytes(blobs["frame_dummy"][offset:offset + 4], "little")
                for offset in (28, 32)] != [names[name][0]["st_value"] for name in (
                    "object.0", "__EH_FRAME_BEGIN__")]:
            return {}
        clone_offset = starts["register_tm_clones"] - code["sh_addr"]
        clone_code = code.data()[clone_offset:clone_offset + 36]
        if (clone_code[0x18:0x1c] != clone_code[0x1c:0x20] or
                clone_code[0x20:0x24] != b"\0\0\0\0"):
            return {}
        if (any((names[name][0]["st_value"] & ~1) != starts["Reset_Handler"] + offset
                for name, offset in labels.items()) or
                (names["Default_Handler"][0]["st_value"] & ~1) !=
                (names["ADC_IRQHandler"][0]["st_value"] & ~1) or
                int.from_bytes(vectors.data()[4:8], "little") != names["Reset_Handler"][0]["st_value"] or
                constructors.data() != names["frame_dummy"][0]["st_value"].to_bytes(4, "little")):
            return {}
        frames = {name: 0 for name in ("Reset_Handler", *labels, "ADC_IRQHandler",
                                            "register_tm_clones")}
        frames["frame_dummy"] = 8
        return {"frames": frames,
                "calls": {starts["__libc_init_array"] + 0x28:
                          {"caller": "__libc_init_array", "target": None},
                          starts["__libc_init_array"] + 0x32:
                          {"caller": "__libc_init_array", "target": "frame_dummy"}},
                "branches": {starts["register_tm_clones"] + 0x14:
                             {"caller": "register_tm_clones", "target": None}},
                "proof": "reviewed_startup_code_and_elf_arrays",
                "elf_sha256": digest(elf_path)}


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


def cfi_stack_bytes(rows: list[tuple[int, int]]) -> int | None:
    if not rows or any(reg != 13 or type(offset) is not int or offset < 0
                       for reg, offset in rows):
        return None
    return max(offset for _, offset in rows)


def dwarf_frame_evidence(elf_path: Path) -> dict[str, dict]:
    """Read final ELF CFI for functions absent from compiler stack reports.

    CFI is accepted only when it covers the entire symbol and describes every
    row as a fixed, nonnegative SP-relative CFA. Other unwind forms stay gaps.
    """
    try:
        from elftools.elf.elffile import ELFFile
        from elftools.dwarf.callframe import FDE
    except ImportError as exc:
        raise ValueError("pyelftools is required for final ELF stack evidence") from exc
    evidence = {}
    with elf_path.open("rb") as stream:
        elf = ELFFile(stream)
        symbols = elf.get_section_by_name(".symtab")
        if symbols is None:
            raise ValueError("final ELF has no symbol table")
        dwarf = elf.get_dwarf_info()
        frames = []
        for entry in dwarf.CFI_entries():
            if not isinstance(entry, FDE):
                continue
            start = entry["initial_location"]
            end = start + entry["address_range"]
            if end <= start:
                continue
            rows = [(row["cfa"].reg, row["cfa"].offset)
                    for row in entry.get_decoded().table]
            maximum = cfi_stack_bytes(rows)
            if maximum is not None:
                frames.append((start, end, maximum))
        functions = [symbol for symbol in symbols.iter_symbols()
                     if symbol["st_info"]["type"] == "STT_FUNC" and symbol.name]
        function_starts = {symbol["st_value"] & ~1 for symbol in functions}
        for symbol in functions:
            start = symbol["st_value"] & ~1
            end = start + symbol["st_size"]
            if end > start:
                covering = [frame for frame in frames
                            if frame[0] <= start and end <= frame[1]]
            else:
                # Some linked newlib assembly symbols have zero ELF size.
                # An exact FDE can bound them only when no other function
                # begins inside that FDE's address range.
                covering = [frame for frame in frames
                            if frame[0] == start and
                            not any(start < other < frame[1]
                                    for other in function_starts)]
            if len(covering) != 1:
                continue
            low, high, maximum = covering[0]
            evidence[symbol.name] = {"frame_bytes": maximum,
                                     "fde_start": low, "fde_end": high,
                                     "proof": "final_elf_sp_relative_cfi"}
    return evidence


def dwarf_return_evidence(elf_path: Path, disassembly: str) -> dict[int, dict]:
    """Prove stack-pop PC returns using instruction bytes and final ELF CFI."""
    try:
        from elftools.elf.elffile import ELFFile
        from elftools.dwarf.callframe import FDE
    except ImportError as exc:
        raise ValueError("pyelftools is required for final ELF return evidence") from exc
    candidates = []
    caller, entry = None, None
    for line in disassembly.splitlines():
        header = re.match(r"^([0-9a-fA-F]+) <(.+)>:$", line.strip())
        if header:
            entry, caller = int(header[1], 16), header[2]
            continue
        instruction = re.match(
            r"^\s*([0-9a-fA-F]+):\s+f85d\s+(fb[0-9a-fA-F]{2})\s+"
            r"ldr\.w\s+pc,\s*\[sp\],\s*#(\d+)\s*$", line)
        if instruction is None or caller is None:
            continue
        address = int(instruction[1], 16)
        increment = int(instruction[3])
        if increment == 0 or increment > 255 or increment % 4 != 0 or \
                int(instruction[2], 16) != 0xfb00 | increment:
            continue
        candidates.append((address, entry, caller, increment))
    evidence = {}
    with elf_path.open("rb") as stream:
        dwarf = ELFFile(stream).get_dwarf_info()
        frames = [item for item in dwarf.CFI_entries() if isinstance(item, FDE)]
        for address, entry, caller, increment in candidates:
            covering = [item for item in frames
                        if item["initial_location"] == entry and
                        address + 4 <= entry + item["address_range"]]
            if len(covering) != 1:
                continue
            rows = [row for row in covering[0].get_decoded().table
                    if row["pc"] <= address]
            if not rows:
                continue
            row = rows[-1]
            return_rule = row.get(14)
            if (row["cfa"].reg == 13 and row["cfa"].offset == increment and
                    return_rule is not None and
                    return_rule.type == "OFFSET" and
                    return_rule.arg == -increment):
                evidence[address] = {"caller": caller, "increment": increment,
                                     "fde_start": entry,
                                     "proof": "final_elf_saved_lr_stack_pop"}
    return evidence


def dwarf_interior_tail_evidence(disassembly: str,
                                 frame_evidence: dict[str, dict]) -> dict[int, dict]:
    """Bound direct interior entries by their final-ELF owner's entire CFI frame."""
    headers, code_addresses, candidates = {}, set(), []
    caller = None
    condition = r"(?:eq|ne|cs|hs|cc|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le|al)?"
    for line in disassembly.splitlines():
        header = re.match(r"^([0-9a-fA-F]+) <(.+)>:$", line.strip())
        if header:
            caller = header[2]
            headers[caller] = int(header[1], 16)
            continue
        instruction = re.match(
            r"^\s*([0-9a-fA-F]+):\s+(?:[0-9a-fA-F]{2,8}\s+)+"
            r"([.a-z][a-z0-9.]*)\s*(.*)", line)
        if instruction is None or instruction[2].startswith("."):
            continue
        code_addresses.add(int(instruction[1], 16))
        if not (re.fullmatch(r"b" + condition + r"(?:\.w|\.n)?", instruction[2])
                or instruction[2] in ("cbz", "cbnz")):
            continue
        target = re.search(r"\b([0-9a-fA-F]+)\s+<([^>]+)\+0x([0-9a-fA-F]+)>",
                           instruction[3])
        if target and target[2] != caller:
            candidates.append((int(target[1], 16), target[2], int(target[3], 16)))
    evidence = {}
    starts = sorted(set(headers.values()))
    for destination, owner, offset in candidates:
        entry = headers.get(owner)
        frame = frame_evidence.get(owner)
        if entry is None or frame is None or destination != entry + offset or \
                destination not in code_addresses:
            continue
        next_start = next((address for address in starts if address > entry), None)
        if (next_start is not None and destination >= next_start) or not (
                frame["fde_start"] <= entry <= destination < frame["fde_end"]):
            continue
        evidence[destination] = {"owner": owner, "frame_bytes": frame["frame_bytes"],
                                 "proof": "final_elf_sp_relative_cfi_interior"}
    return evidence


def dwarf_internal_call_evidence(elf_path: Path, disassembly: str) -> dict[int, dict]:
    """Prove local BL helpers stay within one unchanged CFI stack frame."""
    try:
        from elftools.elf.elffile import ELFFile
        from elftools.dwarf.callframe import FDE
    except ImportError as exc:
        raise ValueError("pyelftools is required for internal-call evidence") from exc
    rows, candidates = [], []
    caller, entry = None, None
    condition = r"(?:eq|ne|cs|hs|cc|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le|al)?"
    for line in disassembly.splitlines():
        header = re.match(r"^([0-9a-fA-F]+) <(.+)>:$", line.strip())
        if header:
            entry, caller = int(header[1], 16), header[2]
            continue
        instruction = re.match(
            r"^\s*([0-9a-fA-F]+):\s+(?:[0-9a-fA-F]{2,8}\s+)+"
            r"([.a-z][a-z0-9.]*)\s*(.*)", line)
        if instruction is None or instruction[2].startswith("."):
            continue
        address, op, operands = int(instruction[1], 16), instruction[2], instruction[3]
        rows.append((address, op, operands, caller))
        if not re.fullmatch(r"blx?" + condition + r"(?:\.w|\.n)?", op):
            continue
        target = re.search(r"\b([0-9a-fA-F]+)\s+<([^>]+)\+0x([0-9a-fA-F]+)>",
                           operands)
        if target and target[2] == caller and int(target[1], 16) == entry + int(target[3], 16):
            candidates.append((address, int(target[1], 16), entry, caller))

    code_addresses = {address for address, _, _, _ in rows}
    evidence = {}
    with elf_path.open("rb") as stream:
        dwarf = ELFFile(stream).get_dwarf_info()
        frames = [item for item in dwarf.CFI_entries() if isinstance(item, FDE)]
        for source, target, entry, caller in candidates:
            if target <= source or target not in code_addresses:
                continue
            covering = [item for item in frames
                        if item["initial_location"] == entry and
                        target < entry + item["address_range"]]
            if len(covering) != 1:
                continue
            end = entry + covering[0]["address_range"]
            cfi_rows = covering[0].get_decoded().table
            if cfi_stack_bytes([(row["cfa"].reg, row["cfa"].offset)
                                for row in cfi_rows]) is None:
                continue
            source_row = next((row for row in reversed(cfi_rows) if row["pc"] <= source), None)
            target_row = next((row for row in reversed(cfi_rows) if row["pc"] <= target), None)
            if source_row is None or target_row is None:
                continue
            source_ra, target_ra = source_row.get(14), target_row.get(14)
            if (source_row["cfa"].reg != 13 or target_row["cfa"].reg != 13 or
                    source_row["cfa"].offset != target_row["cfa"].offset or
                    source_ra is None or target_ra is None or
                    source_ra.type != "OFFSET" or target_ra.type != "OFFSET" or
                    source_ra.arg != target_ra.arg or
                    not -source_row["cfa"].offset <= source_ra.arg < 0):
                continue
            # A helper that calls again or branches back to the BL can grow
            # the stack repeatedly even when its CFI row matches the caller.
            unsafe = False
            for address, op, operands, _ in rows:
                if not target <= address < end:
                    continue
                if (op in ("tbb", "tbh") or
                        (re.fullmatch(r"bx" + condition + r"(?:\.w|\.n)?", op)
                         and operands.strip() != "lr") or
                        (op.startswith(("ldr", "mov", "add", "pop")) and
                         re.search(r"\bpc\b", operands))):
                    unsafe = True
                    break
                if re.fullmatch(r"blx?" + condition + r"(?:\.w|\.n)?", op):
                    unsafe = True
                    break
                if (re.fullmatch(r"b" + condition + r"(?:\.w|\.n)?", op)
                        or op in ("cbz", "cbnz")):
                    branch = re.search(r"\b([0-9a-fA-F]+)\s+<", operands)
                    if branch and entry <= int(branch[1], 16) < target:
                        unsafe = True
                        break
            if not unsafe:
                evidence[source] = {"caller": caller, "target": target,
                                    "fde_start": entry,
                                    "proof": "final_elf_same_cfi_frame_no_reentry"}
    return evidence


def analyze(disassembly: str, frames: dict[str, int],
            proven_returns: dict[int, dict] | None = None,
            proven_interior_tails: dict[int, dict] | None = None,
            proven_internal_calls: dict[int, dict] | None = None,
            proven_printf: dict[int, dict] | None = None,
            proven_startup_calls: dict[int, dict] | None = None,
            proven_startup_branches: dict[int, dict] | None = None) -> dict:
    graph: dict[str, set[str]] = {}
    indirect, tails, internal_calls = [], [], []
    header_addresses, tail_addresses = {}, []
    condition = r"(?:eq|ne|cs|hs|cc|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le|al)?"
    width = r"(?:\.w|\.n)?"
    caller = None
    for line in disassembly.splitlines():
        header = re.match(r"^([0-9a-fA-F]+) <(.+)>:$", line.strip())
        if header:
            caller = header[2]
            header_addresses[caller] = int(header[1], 16)
            graph.setdefault(caller, set())
            continue
        instruction = re.match(r"^\s*[0-9a-fA-F]+:\s+(?:[0-9a-fA-F]{2,8}\s+)+([a-z][a-z0-9.]*)\s*(.*)", line)
        if not caller or not instruction:
            continue
        op, operands = instruction.groups()
        address = int(line.split(":", 1)[0], 16)
        target = re.search(r"<([^>]+)>", operands)
        # Match the instruction class first: BLE is B.LE, not a BL call.
        # Conditional calls in IT blocks retain their taken execution path.
        if re.fullmatch(r"blx?" + condition + width, op):
            if target:
                graph[caller].add(target[1])
                if "+0x" in target[1]:
                    internal_calls.append({"caller": caller, "target": target[1],
                                           "instruction": line.strip()})
            elif (proven_printf is not None and address in proven_printf and
                  proven_printf[address]["caller"] == caller and
                  proven_printf[address]["target"] == "__ssputs_r"):
                graph[caller].add("__ssputs_r")
            elif (proven_startup_calls is not None and address in proven_startup_calls and
                  proven_startup_calls[address]["caller"] == caller):
                if proven_startup_calls[address]["target"] is not None:
                    graph[caller].add(proven_startup_calls[address]["target"])
            else:
                indirect.append({"caller": caller, "instruction": line.strip(),
                                 "kind": "register_call"})
        elif (re.fullmatch(r"b" + condition + width, op)
              or op in ("cbz", "cbnz")) and target:
            if target[1].split("+0x")[0] != caller:
                tails.append({"caller": caller, "target": target[1]})
                destination = re.search(r"\b([0-9a-fA-F]+)\s+<", operands)
                tail_addresses.append(int(destination[1], 16) if destination else None)
        elif op in ("tbb", "tbh"):
            # Table entries are data, not annotated branch operands. Until
            # their bounds/targets are proven, even a local switch is unknown.
            indirect.append({"caller": caller, "instruction": line.strip(),
                             "kind": "table_branch"})
        elif ((re.fullmatch(r"bx" + condition + width, op) and operands.strip() != "lr")
              or (op.startswith(("ldr", "mov")) and re.match(r"pc\s*,", operands))):
            if (proven_returns is not None and address in proven_returns and
                    proven_returns[address]["caller"] == caller):
                continue
            if (proven_startup_branches is not None and address in proven_startup_branches and
                    proven_startup_branches[address]["caller"] == caller and
                    op == "bx" and operands.strip() == "r3"):
                continue
            if (proven_printf is not None and address in proven_printf and
                    proven_printf[address]["caller"] == caller and
                    proven_printf[address]["target"] is None and
                    op == "ldr.w" and operands.strip() == "pc, [r1, r3, lsl #2]"):
                continue
            indirect.append({"caller": caller, "instruction": line.strip(),
                             "kind": "register_branch" if op.startswith("bx") else "pc_write"})
    direct_edges = {k: sorted(v) for k, v in sorted(graph.items())}
    if proven_printf:
        for callee, expected in (("_printf_i", {"_svfiprintf_r"}),
                                 ("_printf_common", {"_printf_i"})):
            actual = {source for source, targets in graph.items() if callee in targets}
            if actual != expected:
                raise ValueError(f"reviewed nano printf caller set changed: {callee}: {actual}")
    # An exact entry branch is bounded by the conservative sum of both known
    # frames. Interior or absent targets have no equivalent entry-frame proof.
    unresolved_tails = []
    for transfer, destination in zip(tails, tail_addresses):
        if destination is not None and header_addresses.get(transfer["target"]) == destination:
            continue
        owner = transfer["target"].split("+0x")[0]
        if (destination is not None and proven_interior_tails is not None and
                destination in proven_interior_tails and
                proven_interior_tails[destination]["owner"] == owner):
            continue
        unresolved_tails.append(transfer)
    # An internal BL entry is not covered by the owner's prologue/frame proof.
    # Follow its owner for diagnostic reachability, retaining an explicit gap.
    # A local subroutine is not necessarily recursion through the full entry.
    for transfer in internal_calls:
        caller, target = transfer["caller"], transfer["target"]
        owner = target.split("+0x")[0]
        graph[caller].discard(target)
        if owner != caller:
            graph[caller].add(owner)
    unresolved_internal_calls = [transfer for transfer in internal_calls
                                 if proven_internal_calls is None or
                                 int(transfer["instruction"].split(":", 1)[0], 16)
                                 not in proven_internal_calls]
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
            "unresolved_tail_transfers": [t for t in unresolved_tails
                                          if t["caller"] in reachable],
            "internal_calls": [t for t in internal_calls if t["caller"] in reachable],
            "unresolved_internal_calls": [t for t in unresolved_internal_calls
                                          if t["caller"] in reachable],
            "cycle_reachable": bool(reachable & cycle_nodes),
        }
    return {"roots": roots, "frames": resolved,
            "machine_frame_evidence": machine_frames,
            "direct_edges": direct_edges,
            "call_edges": {k: sorted(v) for k, v in sorted(graph.items())},
            "root_gaps": root_gaps,
            "frame_sum_policy": "sum known direct/tail/table-candidate frames without tail-release credit; "
                                "exact-entry and final-CFI-bounded interior tails use both frames; "
                                "unproved interior tails remain gaps; "
                                "same-CFI local calls without reentry use the owner frame; "
                                "other internal calls remain gaps; "
                                "unknown frames omitted; cycles unbounded",
            "missing_frames": missing, "indirect_transfers": indirect,
            "internal_calls": internal_calls,
            "unresolved_internal_calls": unresolved_internal_calls,
            "table_target_evidence": tables,
            "tail_transfers": tails, "unresolved_tail_transfers": unresolved_tails,
            "cycles": sorted(cycles),
            "complete": bool(graph) and not (missing or indirect or unresolved_tails
                                            or unresolved_internal_calls or cycles)}


def check(elf: Path, map_path: Path, manifest: Path, objdump: Path, output: Path,
          report_only: bool = False) -> int:
    report = {"schema_version": 1, "status": "failed"}
    try:
        frames = load(verify_evidence(elf, map_path, manifest))
        cfi_frames = dwarf_frame_evidence(elf)
        for name, item in cfi_frames.items():
            frames[name] = max(frames.get(name, 0), item["frame_bytes"])
        startup = reviewed_startup_evidence(elf)
        for name, size in startup.get("frames", {}).items():
            frames[name] = max(frames.get(name, 0), size)
        disassembly = subprocess.run([str(objdump), "-d", str(elf)], check=True,
                                     capture_output=True, text=True, timeout=60).stdout
        output.with_suffix(".disassembly.txt").write_text(disassembly, encoding="utf-8")
        returns = dwarf_return_evidence(elf, disassembly)
        interior_tails = dwarf_interior_tail_evidence(disassembly, cfi_frames)
        dwarf_calls = dwarf_internal_call_evidence(elf, disassembly)
        dmul_call = reviewed_dmul_internal_call(elf)
        if set(dwarf_calls) & set(dmul_call):
            raise ValueError("duplicate internal-call proof")
        internal_calls = dict(dwarf_calls)
        internal_calls.update(dmul_call)
        printf_targets = reviewed_nano_printf_targets(elf)
        analysis = analyze(disassembly, frames, returns, interior_tails,
                           internal_calls, printf_targets, startup.get("calls"),
                           startup.get("branches"))
        if "main" not in analysis["frames"]:
            raise ValueError("missing final main stack frame")
        report.update(analysis)
        report["dwarf_frame_evidence"] = cfi_frames
        report["dwarf_return_evidence"] = returns
        report["dwarf_interior_tail_evidence"] = interior_tails
        report["dwarf_internal_call_evidence"] = dwarf_calls
        report["reviewed_dmul_internal_evidence"] = dmul_call
        report["reviewed_startup_evidence"] = startup
        report["reviewed_nano_printf_evidence"] = printf_targets
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
