#ifndef A300_FIRMWARE_LAYOUT_H
#define A300_FIRMWARE_LAYOUT_H

#define FW_FLASH_BASE   0x08000000UL
#define FW_FLASH_END    0x08020000UL
#define BOOT_FLASH_BASE 0x08000000UL
#define BOOT_FLASH_SIZE 0x00006000UL
#define APP_FLASH_BASE  0x08006000UL
#define APP_FLASH_SIZE  0x0001A000UL
#define FW_SRAM_BASE    0x20000000UL
#define FW_SRAM_SIZE    0x00006000UL

#if (BOOT_FLASH_BASE + BOOT_FLASH_SIZE) != APP_FLASH_BASE
#error "Bootloader and App regions must be contiguous"
#endif
#if (APP_FLASH_BASE + APP_FLASH_SIZE) != FW_FLASH_END
#error "App region must end at the N32L406CBL7 Flash limit"
#endif

#endif
