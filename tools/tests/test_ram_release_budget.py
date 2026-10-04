"""Complete RAM gate and fail-closed exception-policy regressions."""
import copy
import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import exception_stack_guard
from exception_stack_guard import assess_exception_stack
from map_ram_guard import run


def rejects(call, message):
    try:
        call()
    except ValueError:
        return
    raise AssertionError(message)


def main():
    build = Path(sys.argv[1])
    root = Path(__file__).resolve().parents[2]
    elf = build / "a300_firmware.elf"
    analysis = json.loads((build / "stack-analysis.json").read_text())
    profile = json.loads((build / "flash-build-profile.json").read_text())
    result = assess_exception_stack(elf, analysis, profile, root)
    assert result["exception_stack_bytes"] == 584
    assert analysis["status"] == "incomplete"
    damaged = copy.deepcopy(analysis)
    damaged["root_gaps"]["main"]["indirect_transfers"].append({"caller": "main"})
    rejects(lambda: assess_exception_stack(elf, damaged, profile, root),
            "unknown reachable call was accepted")
    damaged = copy.deepcopy(analysis)
    damaged["root_gaps"]["UART4_IRQHandler"]["missing_frames"].append("unknown_irq_frame")
    rejects(lambda: assess_exception_stack(elf, damaged, profile, root),
            "unknown IRQ frame was accepted")
    damaged_profile = copy.deepcopy(profile)
    damaged_profile["configuration"]["cflags"] = "-mcpu=cortex-m4"
    rejects(lambda: assess_exception_stack(elf, analysis, damaged_profile, root),
            "changed FPU configuration was accepted")
    with patch.dict(exception_stack_guard.REVIEWED_FILES,
                    {"bootloader/src/platform_n32l406.c": "0" * 64}):
        rejects(lambda: assess_exception_stack(elf, analysis, profile, root),
                "changed Bootloader jump contract was accepted")
    with patch.dict(exception_stack_guard.REVIEWED_FILES,
                    {"src/hw_init.c": "0" * 64}):
        rejects(lambda: assess_exception_stack(elf, analysis, profile, root),
                "changed IRQ priority policy was accepted")
    with TemporaryDirectory() as temp:
        changed_elf = Path(temp) / "changed.elf"
        data = bytearray(elf.read_bytes())
        from elftools.elf.elffile import ELFFile
        with elf.open("rb") as stream:
            vector = ELFFile(stream).get_section_by_name(".isr_vector")
            assert vector is not None
            offset = vector["sh_offset"]
        data[offset + 24 * 4] ^= 1
        changed_elf.write_bytes(data)
        changed_profile = copy.deepcopy(profile)
        changed_profile["elf_sha256"] = hashlib.sha256(data).hexdigest()
        rejects(lambda: assess_exception_stack(changed_elf, analysis, changed_profile, root),
                "changed IRQ vector was accepted")
    assert run("app", build / "a300_firmware.map") == 0
    budget = json.loads((build / "ram-budget.json").read_text())
    assert budget["standalone_stack_report_status"] == "incomplete"
    assert budget["reviewed_execution_roots_status"] == "complete"
    print("complete RAM release budget: PASS")


if __name__ == "__main__":
    main()
