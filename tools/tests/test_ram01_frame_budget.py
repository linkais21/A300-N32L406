"""Necessary RAM-01 frame budget, using hash-bound final-link evidence.

This regression is NOT whole-program stack acceptance: release gates must
still account for library frames, indirect calls, heap and IRQ nesting.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stack_usage_guard import digest, verify_evidence
from map_ram_guard import SRAM_BASE, SRAM_BYTES, RUNTIME_GAP_BYTES, hard_heap_reservation, static_sram


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
    assert not any(item["kind"] == "table_branch" for item in
                   analysis["root_gaps"]["main"]["indirect_transfers"]), (
        "main still reaches an unbounded compiler jump table")
    assert not any(item["caller"] == "agnss_process" for item in
                   analysis["root_gaps"]["main"]["indirect_transfers"]), (
        "AGNSS vendor injection still uses an unbounded callback")
    assert not any(item["caller"].startswith(("f39_apply_effects", "f39_execute_deferred",
                                               "execute_config")) for item in
                   analysis["root_gaps"]["main"]["indirect_transfers"]), (
        "production F39 service calls still have unknown targets")
    assert not any(item["caller"].startswith(("at_config_process", "at_config_execute_sms"))
                   for item in analysis["root_gaps"]["main"]["indirect_transfers"]), (
        "production SMS send/reset still use callback pointers")
    assert not any(item["caller"] == "at_config_execute_text_response"
                   for item in analysis["root_gaps"]["main"]["indirect_transfers"]), (
        "production text-command ACK/reply still uses callback pointers")
    assert not any(item["caller"] in ("sms_send_complete", "service_after_commands",
                                      "ec800m_process") for item in
                   analysis["root_gaps"]["main"]["indirect_transfers"]), (
        "production SMS/modem dispatch still uses unknown callback targets")
    assert not any(item["caller"] in ("uECC_verify", "uECC_vli_modMult_fast")
                   for item in analysis["root_gaps"]["main"]["indirect_transfers"]), (
        "production secp256r1 signature path still uses curve callbacks")
    assert not any(item["caller"] in ("_printf_common", "_printf_i")
                   for item in analysis["root_gaps"]["main"]["indirect_transfers"]), (
        "linked nano printf callback/table still lacks final-ELF target proof")
    assert not analysis["root_gaps"]["main"]["unresolved_internal_calls"], (
        "main still reaches an unbounded libgcc interior call")
    assert not analysis["root_gaps"]["Reset_Handler"]["missing_frames"], (
        "startup still has unbounded assembly/constructor frames")
    assert not analysis["root_gaps"]["Reset_Handler"]["indirect_transfers"], (
        "startup constructor targets are not proven from final ELF arrays")
    assert not analysis["root_gaps"]["ADC_IRQHandler"]["missing_frames"], (
        "ADC default IRQ frame is not proven")
    assert analysis["frames"]["main"] <= 256, (
        "boot-only scratch remains in the permanent main-loop stack frame")
    # A full configuration transaction retains a large candidate on its
    # stack. Error formatting must run after that frame has returned.
    edges = analysis["call_edges"]
    config_entries = [name for name in edges if name.startswith("execute_config")]
    assert config_entries, "missing final-link F39 config transaction"
    pending = list(config_entries)
    reachable = set()
    while pending:
        name = pending.pop()
        if name not in reachable:
            reachable.add(name)
            pending.extend(edges.get(name, []))
    assert not any("printf" in name or name in ("failure", "reply_append")
                   for name in reachable), (
        "F39 config transaction still nests reply formatting")
    map_text = map_path.read_text()
    static = static_sram(map_text)
    heap_start, heap_limit = hard_heap_reservation(map_text)
    assert heap_start - SRAM_BASE >= static
    available = SRAM_BASE + SRAM_BYTES - heap_limit
    frames = analysis["known_main_frame_sum"]
    # Direct modem dispatch exposes the JT808 -> F39 -> Flash write path.
    assert frames <= 2880, "main-loop phase frame exceeds reviewed modem/JT808/F39/Flash chain"
    assert available - frames >= RUNTIME_GAP_BYTES, (
        f"known frames={frames}, hard heap={heap_limit - heap_start}, "
        f"remaining after heap={available - frames} < {RUNTIME_GAP_BYTES}; "
        "this is a necessary budget before IRQ and unknown frames")
    print(f"RAM-01 necessary frame budget PASS: frames={frames}, "
          f"remaining_after_heap={available - frames}; whole-program bound still unproven")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
