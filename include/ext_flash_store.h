#ifndef EXT_FLASH_STORE_H
#define EXT_FLASH_STORE_H
#include <stdint.h>
#include <stdbool.h>
#include "ext_flash_layout.h"
bool ext_flash_read(ext_flash_owner_t owner, uint32_t addr, void *buf, uint32_t len);
bool ext_flash_write_verified(ext_flash_owner_t owner, uint32_t addr, const void *buf, uint32_t len);
bool ext_flash_erase(ext_flash_owner_t owner, uint32_t addr, uint32_t len);
bool ext_flash_try_lock(ext_flash_owner_t owner);
bool ext_flash_try_lock_now(ext_flash_owner_t owner);
void ext_flash_unlock(ext_flash_owner_t owner);
#endif
