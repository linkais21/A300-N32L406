"""Necessary RAM-01 frame budget, using hash-bound final-link evidence.

This regression is NOT whole-program stack acceptance: release gates must
still account for library frames, indirect calls, heap and IRQ nesting.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stack_usage_guard import digest, verify_evidence
from map_ram_guard import static_sram


def main():
    build = Path(sys.argv[1])
    elf = build / "a300_firmware.elf"
    map_path = build / "a300_firmware.map"
    manifest = build / "stack-evidence.json"
    verify_evidence(elf, map_path, manifest)
    analysis = json.loads((build / "stack-analysis.json").read_text())
    assert analysis["elf_sha256"] == digest(elf)
    assert analysis["map_sha256"] == digest(map_path)
    assert analysis["evidence_sha256"] == digest(manifest)
    available = 24576 - static_sram(map_path.read_text())
    frames = analysis["known_main_frame_sum"]
    assert available - frames >= 4096, (
        f"known frames={frames}, remaining={available - frames} < 4096; "
        "large parent frames consume the runtime margin")
    print(f"RAM-01 necessary frame budget PASS: frames={frames}, "
          f"remaining={available - frames}; whole-program bound still unproven")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
