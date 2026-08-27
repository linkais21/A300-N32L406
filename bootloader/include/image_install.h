#ifndef A300_IMAGE_INSTALL_H
#define A300_IMAGE_INSTALL_H

#include "image_manifest.h"
#include <stdbool.h>

bool install_candidate(const image_manifest_t *manifest);
bool install_resume(uint32_t offset);
bool bootloader_select_image(void);

bool boot_int_flash_erase(uint32_t address, uint32_t length);
bool boot_int_flash_program(uint32_t address, const void *data, uint32_t length);
bool boot_int_flash_read(uint32_t address, void *data, uint32_t length);
void boot_watchdog_feed(void);
void boot_jump_to(uint32_t address);

#endif
