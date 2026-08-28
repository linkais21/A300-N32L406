#ifndef EXT_FLASH_STORE_H
#define EXT_FLASH_STORE_H
#include <stdint.h>
#include <stdbool.h>
#include "ext_flash_layout.h"
typedef enum {
    EXT_FLASH_PROGRAM_NOT_ISSUED = 0,
    EXT_FLASH_PROGRAM_ISSUED_UNCERTAIN,
    EXT_FLASH_PROGRAM_VERIFIED,
} ext_flash_program_result_t;
bool ext_flash_read(ext_flash_owner_t owner, uint32_t addr, void *buf, uint32_t len);
bool ext_flash_write_verified(ext_flash_owner_t owner, uint32_t addr, const void *buf, uint32_t len);
ext_flash_program_result_t ext_flash_write_result(
    ext_flash_owner_t owner, uint32_t addr, const void *buf, uint32_t len);
bool ext_flash_erase(ext_flash_owner_t owner, uint32_t addr, uint32_t len);
bool ext_flash_try_lock(ext_flash_owner_t owner);
bool ext_flash_try_lock_now(ext_flash_owner_t owner);
void ext_flash_unlock(ext_flash_owner_t owner);
#endif
