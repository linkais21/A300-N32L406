"""Reviewed libgcc interior-call evidence fails closed on code changes."""
import sys
import tempfile
from pathlib import Path

from elftools.elf.elffile import ELFFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stack_usage_guard import reviewed_dmul_internal_call


def main():
    elf = Path(sys.argv[1])
    proof = reviewed_dmul_internal_call(elf)
    assert len(proof) == 1
    assert next(iter(proof.values()))["frame_bytes"] == 16
    with elf.open("rb") as stream:
        linked = ELFFile(stream)
        symbol = next(s for s in linked.get_section_by_name(".symtab").iter_symbols()
                      if s.name == "__aeabi_dmul")
        section = linked.get_section(symbol["st_shndx"])
        offset = section["sh_offset"] + (symbol["st_value"] & ~1) - section["sh_addr"]
    mutated = bytearray(elf.read_bytes())
    mutated[offset] ^= 1
    with tempfile.TemporaryDirectory() as directory:
        changed = Path(directory) / "changed.elf"
        changed.write_bytes(mutated)
        assert not reviewed_dmul_internal_call(changed)
    print("libgcc interior-call proof: PASS")


if __name__ == "__main__":
    main()
