#include "ext_flash_store.h"
#include "spi_flash.h"

static volatile ext_flash_owner_t g_owner = EXT_FLASH_OWNER_NONE;
static bool range_ok(uint32_t addr, uint32_t len) { return addr <= FLASH_TOTAL_SIZE && len <= FLASH_TOTAL_SIZE - addr; }
static bool owner_ok(ext_flash_owner_t owner) { return owner != EXT_FLASH_OWNER_NONE && g_owner == owner; }

bool ext_flash_try_lock(ext_flash_owner_t owner)
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
bool ext_flash_erase(ext_flash_owner_t owner, uint32_t addr, uint32_t len)
{
    if (!owner_ok(owner) || !range_ok(addr, len) || (addr % FLASH_SECTOR_SIZE) != 0 || (len % FLASH_SECTOR_SIZE) != 0) return false;
    while (len) {
        if (!spi_flash_erase_sector(addr)) return false;
        addr += FLASH_SECTOR_SIZE; len -= FLASH_SECTOR_SIZE;
    }
    return true;
}
