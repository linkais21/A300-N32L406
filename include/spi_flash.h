#ifndef SPI_FLASH_H
#define SPI_FLASH_H

#include <stdint.h>
#include <stdbool.h>

#define FLASH_PAGE_SIZE   256
#define FLASH_SECTOR_SIZE 4096
#define FLASH_TOTAL_SIZE  (2 * 1024 * 1024)   /* BY25Q16: 16 Mbit = 2 MB */

void     spi_flash_init(void);
uint16_t spi_flash_read_id(void);
void     spi_flash_read(uint32_t addr, uint8_t *buf, uint32_t len);
void     spi_flash_write(uint32_t addr, const uint8_t *buf, uint32_t len);
void     spi_flash_erase_sector(uint32_t addr);
void     spi_flash_erase_chip(void);

#endif
