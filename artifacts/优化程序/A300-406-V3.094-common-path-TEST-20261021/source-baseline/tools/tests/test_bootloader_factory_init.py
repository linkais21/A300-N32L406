"""Host regression tests for the Bootloader factory-initialization state machine."""

from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "factory_init.h"

#define FLASH_SIZE (2U * 1024U * 1024U)
#define SECTOR_SIZE 4096U

static uint8_t flash_data[FLASH_SIZE];
static uint32_t erase_log[32];
static unsigned erase_count, read_count, mark_count, feed_count;
static int fail_erase_at, fail_read_at;
static bool fail_mark;
static bool device_valid;

static const uint32_t expected[] = {
    0x000000UL, 0x001000UL,
    0x100000UL, 0x101000UL,
    0x102000UL, 0x103000UL,
    0x104000UL, 0x105000UL,
};

uint32_t image_crc32(const void *data, uint32_t length)
{
    const uint8_t *p = (const uint8_t *)data;
    uint32_t crc = 0xFFFFFFFFUL;
    while (length--) {
        crc ^= *p++;
        for (uint8_t bit = 0; bit < 8U; ++bit)
            crc = (crc >> 1) ^ (0xEDB88320UL & (uint32_t)-(int32_t)(crc & 1U));
    }
    return ~crc;
}

bool boot_ext_erase(uint32_t address, uint32_t length)
{
    assert(length == SECTOR_SIZE);
    assert(address % SECTOR_SIZE == 0U);
    assert(address + length <= FLASH_SIZE);
    erase_log[erase_count++] = address;
    if (fail_erase_at > 0 && (int)erase_count == fail_erase_at) return false;
    memset(flash_data + address, 0xFF, length);
    return true;
}

bool boot_ext_device_valid(void) { return device_valid; }

bool boot_ext_read(uint32_t address, void *data, uint32_t length)
{
    assert(address + length <= FLASH_SIZE);
    ++read_count;
    if (fail_read_at > 0 && (int)read_count == fail_read_at) return false;
    memcpy(data, flash_data + address, length);
    return true;
}

bool boot_factory_mark_complete(uint32_t completion)
{
    assert(completion == FACTORY_INIT_DONE);
    ++mark_count;
    return !fail_mark;
}

void boot_watchdog_feed(void) { ++feed_count; }

static factory_init_request_t pending_request(void)
{
    factory_init_request_t request = {
        FACTORY_INIT_MAGIC,
        FACTORY_INIT_FORMAT,
        sizeof(factory_init_request_t),
        FACTORY_INIT_GENERATION,
        FACTORY_INIT_SCOPE_ALL,
        FACTORY_INIT_REQUEST_CRC32,
        FACTORY_INIT_COMMIT_MARKER,
        FACTORY_INIT_PENDING,
    };
    return request;
}

static void reset_fixture(void)
{
    memset(flash_data, 0xA5, sizeof flash_data);
    memset(erase_log, 0, sizeof erase_log);
    erase_count = read_count = mark_count = feed_count = 0U;
    fail_erase_at = fail_read_at = 0;
    fail_mark = false;
    device_valid = true;
}

static bool is_target(uint32_t address)
{
    for (unsigned i = 0; i < sizeof expected / sizeof expected[0]; ++i)
        if (address >= expected[i] && address < expected[i] + SECTOR_SIZE) return true;
    return false;
}

static void assert_success_state(void)
{
    assert(erase_count == sizeof expected / sizeof expected[0]);
    for (unsigned i = 0; i < erase_count; ++i) assert(erase_log[i] == expected[i]);
    assert(mark_count == 1U);
    assert(feed_count > 0U);
    for (uint32_t address = 0; address < FLASH_SIZE; address += 257U) {
        uint8_t expected_byte = is_target(address) ? 0xFFU : 0xA5U;
        assert(flash_data[address] == expected_byte);
    }
}

static void test_embedded_request(void)
{
    const factory_init_request_t *request = factory_init_request();
    assert(request != NULL);
    assert(request->magic == FACTORY_INIT_MAGIC);
    assert(request->format_version == FACTORY_INIT_FORMAT);
    assert(request->record_length == sizeof *request);
    assert(request->generation == FACTORY_INIT_GENERATION);
    assert(request->scope == FACTORY_INIT_SCOPE_ALL);
    assert(request->crc32 == FACTORY_INIT_REQUEST_CRC32);
    assert(request->commit_marker == FACTORY_INIT_COMMIT_MARKER);
    assert(request->completion == FACTORY_INIT_PENDING);
}

static void test_success_and_terminal_states(void)
{
    factory_init_request_t request = pending_request();
    reset_fixture();
    assert(factory_init_apply(&request) == FACTORY_INIT_RESULT_APPLIED);
    assert_success_state();

    reset_fixture();
    request.completion = FACTORY_INIT_DONE;
    assert(factory_init_apply(&request) == FACTORY_INIT_RESULT_ALREADY_DONE);
    assert(erase_count == 0U && read_count == 0U && mark_count == 0U);

    reset_fixture();
    request = pending_request();
    request.magic ^= 1U;
    assert(factory_init_apply(&request) == FACTORY_INIT_RESULT_ERROR);
    assert(erase_count == 0U && mark_count == 0U);

    reset_fixture();
    request = pending_request();
    request.completion = 0x12345678UL;
    assert(factory_init_apply(&request) == FACTORY_INIT_RESULT_ERROR);
    assert(erase_count == 0U && mark_count == 0U);

    reset_fixture();
    request = pending_request();
    device_valid = false;
    assert(factory_init_apply(&request) == FACTORY_INIT_RESULT_DEVICE_UNAVAILABLE);
    assert(erase_count == 0U && read_count == 0U && mark_count == 0U);
}

static void test_failure_boundaries_converge(void)
{
    factory_init_request_t request = pending_request();
    const unsigned sector_count = sizeof expected / sizeof expected[0];

    for (unsigned failure = 1; failure <= sector_count; ++failure) {
        reset_fixture();
        fail_erase_at = (int)failure;
        assert(factory_init_apply(&request) == FACTORY_INIT_RESULT_ERROR);
        assert(mark_count == 0U);
        fail_erase_at = 0;
        erase_count = read_count = 0U;
        assert(factory_init_apply(&request) == FACTORY_INIT_RESULT_APPLIED);
        assert_success_state();
    }

    for (unsigned failure_sector = 0; failure_sector < sector_count; ++failure_sector) {
        reset_fixture();
        fail_read_at = (int)(failure_sector * (SECTOR_SIZE / 64U) + 1U);
        assert(factory_init_apply(&request) == FACTORY_INIT_RESULT_ERROR);
        assert(mark_count == 0U);
        fail_read_at = 0;
        erase_count = read_count = 0U;
        assert(factory_init_apply(&request) == FACTORY_INIT_RESULT_APPLIED);
        assert_success_state();
    }

    reset_fixture();
    fail_mark = true;
    assert(factory_init_apply(&request) == FACTORY_INIT_RESULT_ERROR);
    assert(mark_count == 1U);
    fail_mark = false;
    erase_count = read_count = mark_count = 0U;
    assert(factory_init_apply(&request) == FACTORY_INIT_RESULT_APPLIED);
    assert_success_state();
}

int main(void)
{
    test_embedded_request();
    test_success_and_terminal_states();
    test_failure_boundaries_converge();
    puts("factory_init C scenarios: PASS");
    return 0;
}
'''


def test_factory_init_c_contract():
    compiler = shutil.which("gcc") or shutil.which("clang")
    assert compiler, "host C compiler is required"
    source = ROOT / "bootloader" / "src" / "factory_init.c"
    header = ROOT / "bootloader" / "include" / "factory_init.h"
    assert source.exists(), f"missing implementation: {source}"
    assert header.exists(), f"missing interface: {header}"

    with tempfile.TemporaryDirectory(prefix="boot_factory_init_") as directory:
        temp = Path(directory)
        harness = temp / "harness.c"
        executable = temp / "factory_init_test.exe"
        harness.write_text(HARNESS, encoding="ascii")
        result = subprocess.run(
            [compiler, "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror",
             "-I", str(ROOT / "bootloader" / "include"),
             "-I", str(ROOT / "include"), str(harness), str(source),
             "-o", str(executable)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        result = subprocess.run([str(executable)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    test_factory_init_c_contract()
    print("test_bootloader_factory_init: PASS")
