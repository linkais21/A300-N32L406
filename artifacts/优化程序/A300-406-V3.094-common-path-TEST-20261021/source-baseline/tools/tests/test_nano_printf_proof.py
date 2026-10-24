"""The reviewed nano formatter proof must be tied to exact final ELF bytes."""
import sys
import tempfile
from pathlib import Path

from elftools.elf.elffile import ELFFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stack_usage_guard import reviewed_nano_printf_targets


def main():
    elf = Path(sys.argv[1])
    targets = reviewed_nano_printf_targets(elf)
    assert len(targets) == 6
    assert sum(item["target"] == "__ssputs_r" for item in targets.values()) == 5
    with elf.open("rb") as stream:
        linked = ELFFile(stream)
        symbol = next(s for s in linked.get_section_by_name(".symtab").iter_symbols()
                      if s.name == "_printf_i")
        section = linked.get_section(symbol["st_shndx"])
        offset = section["sh_offset"] + (symbol["st_value"] & ~1) - section["sh_addr"]
    mutated = bytearray(elf.read_bytes())
    mutated[offset] ^= 1
    with tempfile.TemporaryDirectory() as directory:
        changed = Path(directory) / "changed.elf"
        changed.write_bytes(mutated)
        assert not reviewed_nano_printf_targets(changed)
    print("nano printf final-ELF proof: PASS")


if __name__ == "__main__":
    main()
