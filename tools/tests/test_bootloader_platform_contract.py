import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def require(text: str, needle: str, message: str) -> None:
    assert needle in text, message


def test_platform_is_real_and_bounded():
    makefile = (ROOT / "bootloader" / "Makefile").read_text(encoding="utf-8")
    platform = ROOT / "bootloader" / "src" / "platform_n32l406.c"
    assert platform.exists(), "real N32L406 bootloader platform source is missing"
    source = platform.read_text(encoding="utf-8")
    combined = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (ROOT / "bootloader" / "src").glob("*.c")
    )

    for required in (
        "src/platform_n32l406.c",
        "n32l40x_gpio.c",
        "n32l40x_rcc.c",
        "n32l40x_spi.c",
        "n32l40x_flash.c",
        "n32l40x_iwdg.c",
        "system_n32l40x.c",
        "../src/firmware_signature.c",
        "../third_party/micro-ecc/uECC.c",
    ):
        require(makefile, required, f"Bootloader Makefile missing {required}")

    assert "__attribute__((weak))" not in combined, "release bootloader still has weak hardware hooks"
    require(source, "FLASH_TOTAL_SIZE - length", "external Flash bounds must be overflow-safe")
    require(source, "APP_FLASH_END - length", "internal Flash bounds must be overflow-safe")
    require(source, "GPIO_AF0_SPI1", "PA5/PA6/PA7 SPI1 routing must use AF0")
    assert "GPIO_AF5_SPI1" not in source, "PA5/PA6/PA7 must not use the alternate SPI1 mapping"
    require(source, "0x20006000UL", "jump must enforce the 24 KiB SRAM ceiling")
    require(source, "APP_FLASH_BASE + 1UL", "jump must require a Thumb reset vector in App")
    require(source, "APP_FLASH_END", "jump must enforce the App Flash ceiling")
    for action in ("__disable_irq()", "SysTick->CTRL = 0U", "SCB->VTOR = address", "__set_MSP(msp)"):
        require(source, action, f"safe jump is missing {action}")
    require(source, "__enable_irq();", "App must start with interrupts enabled")
    recovery = source[source.index("void boot_recovery_step"):source.index("uint32_t boot_rollback_counter")]
    assert "__WFI()" not in recovery, \
        "recovery must not sleep indefinitely before the watchdog feed"
    require(recovery, "__NOP();", "recovery must make bounded forward progress")


def test_lkg_preserves_a_verified_signed_package():
    install = (ROOT / "bootloader" / "src" / "image_install.c").read_text(encoding="utf-8")
    assert "boot_ecdsa_sign" not in install, "Bootloader must never create an LKG signature"
    require(install, "verify_external_manifest", "copied LKG package must be re-verified")
    require(install, "sizeof(image_manifest_t) + manifest->image_length",
            "LKG copy must preserve manifest plus payload")
    candidate_install = install[install.index("bool install_candidate"):install.index("bool install_resume")]
    assert "preserve_signed_package_to_lkg" not in candidate_install, \
        "unproven candidate must not overwrite the previous healthy LKG"
    require(install, "r.state == BCR_ACTIVE", "healthy state must trigger candidate promotion")
    require(install, "r.image_version == m.version_counter",
            "only the healthy BCR version may be promoted to LKG")
    active_body = install[install.index("if (r.state == BCR_ACTIVE)"):install.index("if ((r.state == BCR_TRIAL")]
    assert "preserve_signed_package_to_lkg(&m);" in active_body.replace("(void)", "")
    assert "if (!preserve_signed_package_to_lkg(&m)) return false;" not in active_body


def test_bcr_separates_trial_version_from_rollback_floor():
    header = (ROOT / "include" / "boot_contract.h").read_text(encoding="utf-8")
    source = (ROOT / "bootloader" / "src" / "bcr.c").read_text(encoding="utf-8")
    platform = (ROOT / "bootloader" / "src" / "platform_n32l406.c").read_text(encoding="utf-8")
    require(header, "uint32_t rollback_floor;",
            "BCR must preserve the last healthy rollback floor during Trial")
    require(source, "(int32_t)(a - b) > 0", "BCR sequence selection must be wrap-safe")
    require(platform, "record.rollback_floor", "signature rollback checks must use the healthy floor")


def test_main_enters_recovery_if_image_jump_returns():
    compiler = shutil.which("gcc")
    if compiler is None:
        if os.environ.get("REQUIRE_GCC") == "1":
            raise AssertionError("host gcc is required but was not found")
        return

    harness = r'''
#include <stdbool.h>
#include <stdlib.h>

int bootloader_main(void);

bool boot_platform_init(void) { return true; }
bool boot_reset_was_fault_or_watchdog(void) { return false; }
void bcr_note_trial_reset(bool fault_or_watchdog) { (void)fault_or_watchdog; }
bool bootloader_select_image(void) { return true; }
void boot_watchdog_feed(void) {}
void boot_recovery_step(void)
{
    static unsigned calls;
    if (++calls == 1025U) exit(0);
}

int main(void)
{
    (void)bootloader_main();
    return 9;
}
'''
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        harness_path = temp / "bootloader_main_harness.c"
        main_object = temp / "bootloader_main.o"
        executable = temp / "bootloader_main_test.exe"
        harness_path.write_text(harness, encoding="ascii")
        subprocess.run(
            [compiler, "-std=c99", "-Dmain=bootloader_main",
             "-I", str(ROOT / "bootloader" / "include"),
             "-I", str(ROOT / "include"),
             "-c", str(ROOT / "bootloader" / "src" / "main.c"),
             "-o", str(main_object)],
            check=True,
        )
        subprocess.run(
            [compiler, str(harness_path), str(main_object), "-o", str(executable)],
            check=True,
        )
        result = subprocess.run([str(executable)], check=False)
        assert result.returncode == 0, (
            "Bootloader main returned after an image jump returned instead of "
            "remaining in watchdog-serviced recovery"
        )


def test_invalid_app_paths_report_recovery_to_main():
    main = (ROOT / "bootloader" / "src" / "main.c").read_text(encoding="utf-8")
    install = (ROOT / "bootloader" / "src" / "image_install.c").read_text(encoding="utf-8")
    require(main, "for (;;) { boot_recovery_step(); boot_watchdog_feed(); }",
            "recovery must remain active and feed the watchdog")
    assert "for (unsigned i=0; i<1024U; ++i)" not in main, \
        "recovery must not terminate after a fixed number of iterations"
    assert install.count("boot_jump_to(APP_FLASH_BASE)") == 5, \
        "test must cover every App jump path"
    assert install.count("boot_jump_to(APP_FLASH_BASE); return false;") == 4, \
        "every compact App jump path must route a returned jump to recovery"
    active_jump = """boot_jump_to(APP_FLASH_BASE);
        return false;"""
    require(install, active_jump, "ACTIVE App jump must route a returned jump to recovery")


def test_external_flash_probe_does_not_block_valid_app_boot():
    platform = (ROOT / "bootloader" / "src" / "platform_n32l406.c").read_text(encoding="utf-8")
    init_body = platform[platform.index("bool boot_platform_init"):platform.index("bool boot_ext_read")]
    assert "return jedec_valid();" not in init_body, \
        "optional external Flash probe must not block booting a valid internal App"
    require(init_body, "jedec_valid();", "initialization should still probe external Flash")


if __name__ == "__main__":
    test_platform_is_real_and_bounded()
    test_lkg_preserves_a_verified_signed_package()
    test_bcr_separates_trial_version_from_rollback_floor()
    test_main_enters_recovery_if_image_jump_returns()
    test_external_flash_probe_does_not_block_valid_app_boot()
    print("test_bootloader_platform_contract: PASS")
