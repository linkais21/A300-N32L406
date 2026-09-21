#include "factory_init.h"
#include "boot_contract.h"
#include "ext_flash_layout.h"
#include "fota_checkpoint.h"
#include "image_verify.h"
#include <stddef.h>

__attribute__((section(".factory_init_request"), used))
static const factory_init_request_t k_factory_init_request = {
    FACTORY_INIT_MAGIC,
    FACTORY_INIT_FORMAT,
    sizeof(factory_init_request_t),
    FACTORY_INIT_GENERATION,
    FACTORY_INIT_SCOPE_ALL,
    FACTORY_INIT_REQUEST_CRC32,
    FACTORY_INIT_COMMIT_MARKER,
    FACTORY_INIT_PENDING,
};

static const uint32_t k_factory_init_sectors[] = {
    EXT_FLASH_CONFIG_SLOT_A_ADDR,
    EXT_FLASH_CONFIG_SLOT_B_ADDR,
    BCR_SLOT_A_ADDR,
    BCR_SLOT_B_ADDR,
    FOTA_CHECKPOINT_SLOT_A,
    FOTA_CHECKPOINT_SLOT_B,
    FOTA_AUTH_SLOT_A,
    FOTA_AUTH_SLOT_B,
};

_Static_assert(FLASH_SECTOR_SIZE == 4096U, "factory init requires 4 KiB sectors");
_Static_assert(EXT_FLASH_CONFIG_SLOT_A_ADDR == 0x000000UL &&
               EXT_FLASH_CONFIG_SLOT_B_ADDR == 0x001000UL &&
               BCR_SLOT_A_ADDR == 0x100000UL && BCR_SLOT_B_ADDR == 0x101000UL &&
               FOTA_CHECKPOINT_SLOT_A == 0x102000UL &&
               FOTA_CHECKPOINT_SLOT_B == 0x103000UL &&
               FOTA_AUTH_SLOT_A == 0x104000UL && FOTA_AUTH_SLOT_B == 0x105000UL,
               "factory init target layout changed");
_Static_assert(FOTA_AUTH_SLOT_B + FLASH_SECTOR_SIZE <=
               EXT_FLASH_RESUME_ADDR + EXT_FLASH_RESUME_SIZE,
               "factory init target exceeds resume region");

const factory_init_request_t *factory_init_request(void)
{
    return &k_factory_init_request;
}

static bool request_valid(const factory_init_request_t *request)
{
    return request != NULL &&
           request->magic == FACTORY_INIT_MAGIC &&
           request->format_version == FACTORY_INIT_FORMAT &&
           request->record_length == sizeof *request &&
           request->generation == FACTORY_INIT_GENERATION &&
           request->scope == FACTORY_INIT_SCOPE_ALL &&
           request->crc32 == FACTORY_INIT_REQUEST_CRC32 &&
           image_crc32(request, (uint32_t)offsetof(factory_init_request_t, crc32)) ==
               request->crc32 &&
           request->commit_marker == FACTORY_INIT_COMMIT_MARKER;
}

static bool sector_is_erased(uint32_t address)
{
    uint8_t buffer[64];
    uint32_t offset = 0U;

    while (offset < FLASH_SECTOR_SIZE) {
        if (!boot_ext_read(address + offset, buffer, sizeof buffer)) return false;
        for (uint32_t i = 0U; i < sizeof buffer; ++i)
            if (buffer[i] != 0xFFU) return false;
        offset += sizeof buffer;
        boot_watchdog_feed();
    }
    return true;
}

factory_init_result_t factory_init_apply(const factory_init_request_t *request)
{
    if (!request_valid(request)) return FACTORY_INIT_RESULT_ERROR;
    if (request->completion == FACTORY_INIT_DONE)
        return FACTORY_INIT_RESULT_ALREADY_DONE;
    if (request->completion != FACTORY_INIT_PENDING)
        return FACTORY_INIT_RESULT_ERROR;
    if (!boot_ext_device_valid()) return FACTORY_INIT_RESULT_ERROR;

    for (uint32_t i = 0U;
         i < (uint32_t)(sizeof k_factory_init_sectors / sizeof k_factory_init_sectors[0]);
         ++i) {
        if (!boot_ext_erase(k_factory_init_sectors[i], FLASH_SECTOR_SIZE) ||
            !sector_is_erased(k_factory_init_sectors[i]))
            return FACTORY_INIT_RESULT_ERROR;
        boot_watchdog_feed();
    }

    if (!boot_factory_mark_complete(FACTORY_INIT_DONE))
        return FACTORY_INIT_RESULT_ERROR;
    return FACTORY_INIT_RESULT_APPLIED;
}
