"""Startup constructor/frame evidence must match the exact linked arrays."""
import sys
import tempfile
from pathlib import Path

from elftools.elf.elffile import ELFFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stack_usage_guard import reviewed_startup_evidence


def main():
    elf = Path(sys.argv[1])
    proof = reviewed_startup_evidence(elf)
    assert len(proof["frames"]) == 8 and len(proof["calls"]) == 2
    with elf.open("rb") as stream:
        linked = ELFFile(stream)
        section = linked.get_section_by_name(".init_array")
        offset = section["sh_offset"]
        symbols = linked.get_section_by_name(".symtab")
        reset = next(item for item in symbols.iter_symbols() if item.name == "Reset_Handler")
        text = linked.get_section(reset["st_shndx"])
        branch_offset = text["sh_offset"] + (reset["st_value"] & ~1) - text["sh_addr"] + 38
    mutated = bytearray(elf.read_bytes())
    mutated[offset] ^= 1
    with tempfile.TemporaryDirectory() as directory:
        changed = Path(directory) / "changed.elf"
        changed.write_bytes(mutated)
        assert not reviewed_startup_evidence(changed)
        mutated = bytearray(elf.read_bytes())
        mutated[branch_offset] ^= 1
        changed.write_bytes(mutated)
        assert not reviewed_startup_evidence(changed)
    print("startup final-ELF proof: PASS")


if __name__ == "__main__":
    main()
