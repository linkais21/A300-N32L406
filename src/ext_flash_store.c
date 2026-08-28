#include "ext_flash_store.h"
#include "spi_flash.h"
#include "config.h"

static volatile ext_flash_owner_t g_owner = EXT_FLASH_OWNER_NONE;
static bool range_ok(uint32_t addr, uint32_t len) { return addr <= FLASH_TOTAL_SIZE && len <= FLASH_TOTAL_SIZE - addr; }
static bool owner_ok(ext_flash_owner_t owner) { return owner != EXT_FLASH_OWNER_NONE && g_owner == owner; }

bool ext_flash_try_lock(ext_flash_owner_t owner)
{
    uint32_t start;
    uint32_t guard;
    if (owner == EXT_FLASH_OWNER_NONE) return false;
    start = TICK_MS();
    guard = SPI_FLASH_TIMEOUT_MS * 1024U + 1U;
    do {
        if (g_owner == EXT_FLASH_OWNER_NONE) { g_owner = owner; return true; }
    } while ((uint32_t)(TICK_MS() - start) < SPI_FLASH_TIMEOUT_MS && guard-- != 0U);
    return false;
}
bool ext_flash_try_lock_now(ext_flash_owner_t owner)
{
    if (owner == EXT_FLASH_OWNER_NONE || g_owner != EXT_FLASH_OWNER_NONE) return false;
    g_owner = owner;
    return true;
}
void ext_flash_unlock(ext_flash_owner_t owner) { if (g_owner == owner) g_owner = EXT_FLASH_OWNER_NONE; }
bool ext_flash_read(ext_flash_owner_t owner, uint32_t addr, void *buf, uint32_t len)
{
    return owner_ok(owner) && buf != 0 && range_ok(addr, len) && spi_flash_read(addr, (uint8_t *)buf, len);
}
bool ext_flash_write_verified(ext_flash_owner_t owner, uint32_t addr, const void *buf, uint32_t len)
{
    if (!owner_ok(owner) || !buf || !range_ok(addr, len) || !spi_flash_write(addr, (const uint8_t *)buf, len)) return false;
    uint8_t verify[256]; const uint8_t *src = (const uint8_t *)buf;
    while (len) {
        uint32_t n = len > sizeof verify ? sizeof verify : len;
        if (!owner_ok(owner) || !spi_flash_read(addr, verify, n)) return false;
        for (uint32_t i = 0; i < n; ++i) if (verify[i] != src[i]) return false;
        addr += n; src += n; len -= n;
    }
    return true;
}
ext_flash_program_result_t ext_flash_write_result(
    ext_flash_owner_t owner, uint32_t addr, const void *buf, uint32_t len)
{
    spi_flash_program_result_t programmed;
    uint8_t verify[256];
    const uint8_t *src = (const uint8_t *)buf;
    uint32_t remaining = len;
    if (!owner_ok(owner) || !buf || !range_ok(addr, len))
        return EXT_FLASH_PROGRAM_NOT_ISSUED;
    programmed = spi_flash_write_result(addr, src, len);
    if (programmed == SPI_FLASH_PROGRAM_NOT_ISSUED)
        return EXT_FLASH_PROGRAM_NOT_ISSUED;
    if (programmed != SPI_FLASH_PROGRAM_COMPLETED)
        return EXT_FLASH_PROGRAM_ISSUED_UNCERTAIN;
    while (remaining != 0U) {
        uint32_t n = remaining > sizeof(verify) ? sizeof(verify) : remaining;
        uint32_t i;
        if (!owner_ok(owner) || !spi_flash_read(addr, verify, n))
            return EXT_FLASH_PROGRAM_ISSUED_UNCERTAIN;
        for (i = 0U; i < n; ++i)
            if (verify[i] != src[i])
                return EXT_FLASH_PROGRAM_ISSUED_UNCERTAIN;
        addr += n;
        src += n;
        remaining -= n;
    }
    return EXT_FLASH_PROGRAM_VERIFIED;
}
bool ext_flash_erase(ext_flash_owner_t owner, uint32_t addr, uint32_t len)
{
    if (!owner_ok(owner) || !range_ok(addr, len) || (addr % FLASH_SECTOR_SIZE) != 0 || (len % FLASH_SECTOR_SIZE) != 0) return false;
    while (len) {
        if (!spi_flash_erase_sector(addr)) return false;
        addr += FLASH_SECTOR_SIZE; len -= FLASH_SECTOR_SIZE;
    }
    return true;
}
