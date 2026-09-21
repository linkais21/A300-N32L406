import os
from pathlib import Path
import re
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
    recovery = source[source.index("void boot_recovery_step"):source.index("bool boot_rollback_counter")]
    assert "__WFI()" not in recovery, \
        "recovery must not sleep indefinitely before the watchdog feed"
    require(recovery, "__NOP();", "recovery must make bounded forward progress")


def test_lkg_preserves_a_verified_signed_package():
    install = (ROOT / "bootloader" / "src" / "image_install.c").read_text(encoding="utf-8")
    assert "boot_ecdsa_sign" not in install, "Bootloader must never create an LKG signature"
    require(install, "verify_external_manifest", "copied LKG package must be re-verified")
    contract = (ROOT / "include" / "boot_contract.h").read_text(encoding="utf-8")
    for item in ("LKG_SLOT_A_BASE 0x0C0000UL", "LKG_SLOT_B_BASE 0x0DB000UL",
                 "LKG_SLOT_SIZE 0x1B000UL", "LKG_SLOT_B_AUTH_ADDR 0x0F6000UL",
                 "LKG_SLOT_A_AUTH_ADDR 0x0FF000UL"):
        require(contract, item, "dual LKG package/auth layout is incomplete")
    require(install, "select_newest_lkg", "recovery must select by committed generation")
    require(install, "write_lkg_transaction", "LKG promotion must be transactional")
    require(install.replace(" ", ""), "FOTA_PACKAGE_HEADER_SIZE+manifest->body_size",
            "LKG copy must preserve header plus body")
    candidate_install = install[install.index("bool install_candidate"):install.index("bool install_resume")]
    assert "preserve_signed_package_to_lkg" not in candidate_install, \
        "unproven candidate must not overwrite the previous healthy LKG"
    require(install, "r.state == BCR_ACTIVE", "healthy state must trigger candidate promotion")
    require(install, "r.image_version == m.version",
            "only the healthy BCR version may be promoted to LKG")
    active_body = install[install.index("if (r.state == BCR_ACTIVE)"):install.index("if ((r.state == BCR_TRIAL")]
    assert "write_lkg_transaction(&m,&r);" in active_body.replace("(void)", "")
    assert "if (!write_lkg_transaction(&m)) return false;" not in active_body
    require(install, "boot_int_flash_erase(target, APP_FLASH_MAX_SIZE)",
            "verified restore must clear stale bytes beyond a shorter image")


def test_legacy_format_is_recovery_only():
    verify = (ROOT / "bootloader" / "src" / "image_verify.c").read_text(encoding="utf-8")
    install = (ROOT / "bootloader" / "src" / "image_install.c").read_text(encoding="utf-8")
    candidate = verify[verify.index("image_verify_result_t verify_candidate"):verify.index("bool verify_external_manifest")]
    assert "verify_legacy_package" not in candidate
    require(install, "verify_legacy_package(LKG_SLOT_A_BASE", "legacy LKG recovery was removed")
    require(install, "verify_legacy_package(FACTORY_BASE", "legacy Factory recovery was removed")


def test_candidate_install_is_page_transactional():
    config = (ROOT / "bootloader" / "include" / "bootloader_config.h").read_text(encoding="utf-8")
    install = (ROOT / "bootloader" / "src" / "image_install.c").read_text(encoding="utf-8")
    require(config, "BOOTLOADER_INTERNAL_PAGE_SIZE 2048UL",
            "N32L406 internal Flash transactions must use 2048-byte pages")
    require(config, "BOOTLOADER_COPY_CHUNK_SIZE 256UL",
            "Flash copy chunks must remain at most 256 bytes")
    candidate = install[install.index("bool install_candidate"):install.index("bool install_resume")]
    require(candidate, "install_resume(0U)",
            "candidate installation must enter through the resumable transaction")
    assert "copy_image(" not in candidate, "candidate path must not use the non-journaled restore copy"
    resume = install[install.index("bool install_resume"):install.index("bool bootloader_select_image")]
    require(resume, "offset != r.transaction_offset",
            "resume must reject offsets that do not match the committed BCR boundary")
    require(resume, "BOOTLOADER_INTERNAL_PAGE_SIZE",
            "resume must erase exactly one internal Flash page")
    require(resume, "transaction_offset % BOOTLOADER_INTERNAL_PAGE_SIZE",
            "pending offsets must remain page aligned except for the final image length")
    require(resume, "memcmp(page, verify",
            "each programmed chunk must be read back and compared immediately")
    require(resume, "page_offset < page_length",
            "the complete programmed page or image tail must be read back before BCR commit")
    require(resume, "r.transaction_offset = page_end",
            "BCR progress must advance only after the whole-page comparison")
    select = install[install.index("bool bootloader_select_image"):]
    require(select, "if (install_resume(r.transaction_offset)) boot_jump_to(APP_FLASH_BASE);",
            "a completed pending install must jump only after Trial is durable")
    require(select, "if (r.state == BCR_RECOVERY) return false;",
            "recovery state must never jump into a stale App")


def test_bcr_separates_trial_version_from_rollback_floor():
    header = (ROOT / "include" / "boot_contract.h").read_text(encoding="utf-8")
    source = (ROOT / "bootloader" / "src" / "bcr.c").read_text(encoding="utf-8")
    platform = (ROOT / "bootloader" / "src" / "platform_n32l406.c").read_text(encoding="utf-8")
    require(header, "uint32_t rollback_floor;",
            "BCR must preserve the last healthy rollback floor during Trial")
    require(source, "(int32_t)(a - b) > 0", "BCR sequence selection must be wrap-safe")
    assert "r.rollback_floor = r.image_version" not in source
    require(platform, "record.rollback_floor", "signature rollback checks must use the healthy floor")


def test_bcr_commit_alternates_from_physically_valid_slot():
    source = (ROOT / "bootloader" / "src" / "bcr.c").read_text(encoding="utf-8")
    require(source, "physically newest valid record",
            "BCR destination must not infer slot identity from sequence parity")
    assert "current.sequence & 1U" not in source


def test_main_enters_recovery_if_image_jump_returns():
    compiler = shutil.which("gcc")
    if compiler is None:
        if os.environ.get("REQUIRE_GCC") == "1":
            raise AssertionError("host gcc is required but was not found")
        return

    harness = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include "factory_init.h"

int bootloader_main(void);
static unsigned stage;
static bool factory_error;
void boot_startup_status(const char *name, int32_t value) {(void)name;(void)value;}

bool boot_platform_init(void) { if (stage != 0U) abort(); stage = 1U; return true; }
const factory_init_request_t *factory_init_request(void)
{
    static const factory_init_request_t request = {0};
    if (stage != 1U) abort();
    stage = 2U;
    return &request;
}
factory_init_result_t factory_init_apply(const factory_init_request_t *request)
{
    if (request == NULL || stage != 2U) abort();
    stage = 3U;
    return factory_error ? FACTORY_INIT_RESULT_ERROR : FACTORY_INIT_RESULT_ALREADY_DONE;
}
bool boot_reset_was_fault_or_watchdog(void) { return false; }
bool bcr_note_trial_reset(bool fault_or_watchdog)
{ (void)fault_or_watchdog; if (stage != 3U) abort(); stage = 4U; return true; }
bool bootloader_select_image(void) { if (stage != 4U) abort(); stage = 5U; return true; }
void boot_watchdog_feed(void) {}
void boot_recovery_step(void)
{
    static unsigned calls;
    if (++calls == 1025U) {
        if (stage != (factory_error ? 3U : 5U)) exit(8);
        exit(0);
    }
}

int main(int argc, char **argv)
{
    (void)argv;
    factory_error = argc > 1;
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
            [compiler, "-I", str(ROOT / "bootloader" / "include"),
             "-I", str(ROOT / "include"), str(harness_path), str(main_object),
             "-o", str(executable)],
            check=True,
        )
        for arguments in ([], ["factory-error"]):
            result = subprocess.run([str(executable), *arguments], check=False)
            assert result.returncode == 0, (
                "Bootloader startup order or watchdog-serviced recovery contract failed"
            )


def test_invalid_app_paths_report_recovery_to_main():
    main = (ROOT / "bootloader" / "src" / "main.c").read_text(encoding="utf-8")
    install = (ROOT / "bootloader" / "src" / "image_install.c").read_text(encoding="utf-8")
    require(main, "for (;;) { boot_recovery_step(); boot_watchdog_feed(); }",
            "recovery must remain active and feed the watchdog")
    assert "for (unsigned i=0; i<1024U; ++i)" not in main, \
        "recovery must not terminate after a fixed number of iterations"
    compact = re.sub(r"\s+", "", install)
    jump = "boot_jump_to(APP_FLASH_BASE);"
    tails = compact.split(jump)[1:]
    assert tails, "Bootloader has no App jump path"
    for index, tail in enumerate(tails):
        before_next_jump = tail.split(jump, 1)[0]
        assert "returnfalse;" in before_next_jump, \
            f"App jump path {index} can continue after boot_jump_to() returns"


def test_external_flash_probe_does_not_block_valid_app_boot():
    platform = (ROOT / "bootloader" / "src" / "platform_n32l406.c").read_text(encoding="utf-8")
    init_body = platform[platform.index("bool boot_platform_init"):platform.index("bool boot_ext_device_valid")]
    assert "return jedec_valid();" not in init_body, \
        "optional external Flash probe must not block booting a valid internal App"
    require(init_body, "jedec_valid();", "initialization should still probe external Flash")


def test_factory_init_completion_is_fixed_and_relocked():
    main = (ROOT / "bootloader" / "src" / "main.c").read_text(encoding="utf-8")
    platform = (ROOT / "bootloader" / "src" / "platform_n32l406.c").read_text(encoding="utf-8")
    compact_platform = re.sub(r"\s+", "", platform)
    require(main, "factory_init_apply(factory_init_request())",
            "factory initialization must run before BCR processing")
    assert main.index("factory_init_apply(factory_init_request())") < main.index("bcr_note_trial_reset")
    require(compact_platform, "FACTORY_INIT_PAGE_ADDR+offsetof(factory_init_request_t,completion)",
            "completion address must be derived from the fixed record contract")
    require(platform, "completion != FACTORY_INIT_DONE",
            "platform hook must reject arbitrary completion values")
    require(platform, "FLASH_ProgramWord", "completion must use one internal word program")
    require(platform, "FACTORY_INIT_PENDING", "completion may only replace the pending word")
    require(platform, "FLASH_Lock();", "internal Flash must be relocked")


if __name__ == "__main__":
    test_platform_is_real_and_bounded()
    test_lkg_preserves_a_verified_signed_package()
    test_legacy_format_is_recovery_only()
    test_bcr_separates_trial_version_from_rollback_floor()
    test_main_enters_recovery_if_image_jump_returns()
    test_external_flash_probe_does_not_block_valid_app_boot()
    test_factory_init_completion_is_fixed_and_relocked()
    print("test_bootloader_platform_contract: PASS")
