"""Reviewed N32L406 interrupt nesting and Cortex-M4F stack bound."""
import hashlib
import re
from pathlib import Path

from elftools.elf.elffile import ELFFile


REVIEWED_FILES = {
    # The installed Bootloader must disable and clear IRQs before changing
    # VTOR/MSP; App priorities are then configured from the reviewed sources.
    "bootloader/src/platform_n32l406.c":
        "fe21e64634680e8ede994a209456802beb2b9ed6a633ed3c6d94df2e5adc7400",
    "bootloader/src/startup_n32l40x.s":
        "e188bc2ac29608538f4ec8dd9170a8fe2f8275d32604aef07918da170b88ab0b",
    "Makefile": "63a13599e2f0dc3620792adf281cd30a8fe88a620f9e72d9b9dcdd5e2ba61212",
    # UART5 RX DMA request selection moved after channel init; NVIC policy is unchanged.
    "src/hw_init.c": "9f59e802fa52405e197c3970f2bda677ee630498196ed9ad97f6c58cd278a99b",
    # Reviewed 2026-10-08: foreground report/0x0056 calls only; handlers,
    # NVIC priorities, HardFault recovery and boot_init unchanged. See IRQ review.
    "src/main.c": "ec26f9e7d6bc6d2518b475ad990f40f7baa117dd196610a2b3ec028256eae369",
    "src/work_mode_sleep.c": "d06e52cf291215ddd1932f3df79135d84f6a5aec2991e4a993285a30fb2bcafe",
    "src/startup_n32l40x.s": "37acc056a5dcc630e520d7d97987e369e281c477e373ce2f706abdfab85fe84f",
    "sdk/Nations.N32L40x_Library.2.2.0/firmware/CMSIS/device/n32l40x.h":
        "56886cd610301b9b37c5b2e1d0bbc71b3c0a805297ddf0c2d34f445e0bafb0cb",
    "sdk/Nations.N32L40x_Library.2.2.0/firmware/CMSIS/core/core_cm4.h":
        "53712d8aefacaebf3faa2370be8c7c6065328a974242f9e315ffc86b3ee852c5",
    "sdk/Nations.N32L40x_Library.2.2.0/firmware/n32l40x_std_periph_driver/src/misc.c":
        "72f0d680871169dc07b0afc57b7210c85cfba462b7097a365c72936264abd6cb",
    "sdk/Nations.N32L40x_Library.2.2.0/firmware/n32l40x_std_periph_driver/inc/misc.h":
        "d6cc5a684174437664d5a9191a968077351ea5109fb1eb69cdd8aa129a9c81ca",
    "sdk/Nations.N32L40x_Library.2.2.0/firmware/CMSIS/device/system_n32l40x.c":
        "dadd03373a4c33c8f35bd97a83c232930947815a8ac68e6561d6a303e7fb91cd",
}

# Group 2 has two preemption bits. Equal preemption priorities cannot nest.
PRIORITIES = {
    3: ("SysTick_Handler", "USART1_IRQHandler"),
    2: ("RTCAlarm_IRQHandler", "TIM8_UP_IRQHandler"),
    1: ("UART4_IRQHandler", "DMA_Channel5_IRQHandler", "EXTI2_IRQHandler",
        "EXTI3_IRQHandler", "EXTI15_10_IRQHandler"),
}
VECTORS = {
    1: "Reset_Handler", 3: "HardFault_Handler", 15: "SysTick_Handler",
    22: "EXTI0_IRQHandler", 24: "EXTI2_IRQHandler", 25: "EXTI3_IRQHandler",
    31: "DMA_Channel5_IRQHandler", 53: "USART1_IRQHandler",
    56: "EXTI15_10_IRQHandler", 57: "RTCAlarm_IRQHandler",
    60: "TIM8_UP_IRQHandler", 63: "UART4_IRQHandler",
}
PRIORITY_APIS = re.compile(
    r"\b(?:NVIC_Init|NVIC_EnableIRQ|NVIC_SetPriority|NVIC_PriorityGroupConfig|"
    r"SysTick_Config)\s*\(|(?:SCB|NVIC)->(?:AIRCR|SHP|IP|ISER|ICER|SHCSR|ICSR)\b"
)


def assess_exception_stack(elf_path: Path, analysis: dict, profile: dict,
                           root: Path) -> dict:
    for name, expected in REVIEWED_FILES.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"IRQ policy source changed: {name}")
    for path in (root / "src").glob("*.c"):
        if PRIORITY_APIS.search(path.read_text(encoding="utf-8")) and path.name not in {
                "hw_init.c", "main.c", "work_mode_sleep.c"}:
            raise ValueError(f"unreviewed priority/exception control: {path.name}")
    for path in (root / "bootloader/src").glob("*.c"):
        if PRIORITY_APIS.search(path.read_text(encoding="utf-8")) and path.name != "platform_n32l406.c":
            raise ValueError(f"unreviewed Bootloader priority/exception control: {path.name}")
    config = profile.get("configuration", {})
    flags = config.get("cflags", "").split()
    if (profile.get("elf_sha256") != hashlib.sha256(elf_path.read_bytes()).hexdigest() or
            "14.3.1" not in config.get("compiler", "") or
            not {"-mcpu=cortex-m4", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard",
                 "-DA300_FIRMWARE_IMAGE=1"}.issubset(flags)):
        raise ValueError("compiler/FPU profile does not match reviewed image")
    with elf_path.open("rb") as stream:
        elf = ELFFile(stream)
        symbols = elf.get_section_by_name(".symtab")
        vector = elf.get_section_by_name(".isr_vector")
        if symbols is None or vector is None or len(vector.data()) != 328:
            raise ValueError("missing or changed vector table")
        linked_names = {item.name for item in symbols.iter_symbols()}
        compact_format = ("-DA300_COMPACT_FORMAT=1" in flags and
                          {"a300_snprintf", "a300_vsnprintf"}.issubset(linked_names) and
                          not {"snprintf", "vsnprintf", "_printf_i", "_printf_common",
                               "_svfiprintf_r", "_svfprintf_r"}.intersection(linked_names))
        names = {name: [item for item in symbols.iter_symbols() if item.name == name]
                 for name in (*set(VECTORS.values()), "Default_Handler")}
        if any(len(items) != 1 for items in names.values()):
            raise ValueError("ambiguous interrupt vector symbol")
        default = names["Default_Handler"][0]["st_value"] | 1
        words = [int.from_bytes(vector.data()[i:i + 4], "little")
                 for i in range(0, len(vector.data()), 4)]
        if words[0] != 0x20006000 or words[2] != default:
            raise ValueError("initial MSP or NMI vector changed")
        for index, word in enumerate(words[1:], start=1):
            expected = names[VECTORS[index]][0]["st_value"] | 1 if index in VECTORS else (
                0 if index in (7, 8, 9, 10, 13) else default)
            if word != expected:
                raise ValueError(f"vector {index} changed")
    roots = analysis.get("root_gaps", {})
    for name, gaps in roots.items():
        if (gaps["missing_frames"] or gaps["indirect_transfers"] or
                gaps["unresolved_tail_transfers"] or
                gaps["unresolved_internal_calls"] or gaps["cycle_reachable"]):
            raise ValueError(f"incomplete reachable stack graph: {name}")
    required = {"main", "Reset_Handler", "ADC_IRQHandler", "HardFault_Handler",
                *PRIORITIES[3], *PRIORITIES[2], *PRIORITIES[1]}
    if not required.issubset(roots) or not required.issubset(analysis.get("roots", {})):
        raise ValueError("missing reviewed execution root")
    nano_proof_count = len(analysis.get("reviewed_nano_printf_evidence", {}))
    if ((nano_proof_count != 6 and not (nano_proof_count == 0 and compact_format)) or
            len(analysis.get("reviewed_dmul_internal_evidence", {})) != 1 or
            len(analysis.get("reviewed_startup_evidence", {}).get("frames", {})) != 8):
        raise ValueError("missing final-link library/startup proof")
    group_frames = [max(analysis["roots"][name]["known_frame_sum"] for name in names)
                    for names in PRIORITIES.values()]
    hardfault = analysis["roots"]["HardFault_Handler"]["known_frame_sum"]
    nmi = analysis["roots"]["ADC_IRQHandler"]["known_frame_sum"]
    # M4F exception: 8 basic words + 18 FP extension words + one alignment
    # word. Reserve full FP state at every level even with lazy stacking.
    hardware_frame = (8 + 18 + 1) * 4
    depth = len(PRIORITIES) + 2  # HardFault and NMI outrank normal interrupts.
    software = sum(group_frames) + hardfault + nmi
    return {"preemption_group": 2, "normal_group_frames": group_frames,
            "hardfault_frame": hardfault, "nmi_frame": nmi,
            "hardware_frame_each": hardware_frame, "max_nested_entries": depth,
            "software_frames": software,
            "exception_stack_bytes": hardware_frame * depth + software}
