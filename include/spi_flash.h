#ifndef SPI_FLASH_H
#define SPI_FLASH_H

#include <stdint.h>
#include <stdbool.h>

#define FLASH_PAGE_SIZE   256
#define FLASH_SECTOR_SIZE 4096
#define FLASH_TOTAL_SIZE  (2 * 1024 * 1024)   /* BY25Q16: 16 Mbit = 2 MB */
#ifndef SPI_FLASH_TIMEOUT_MS
#define SPI_FLASH_TIMEOUT_MS 100U
#endif
#define SPI_FLASH_ERASE_TIMEOUT_MS 500U

typedef enum {
    SPI_FLASH_PROGRAM_NOT_ISSUED = 0,
    SPI_FLASH_PROGRAM_ISSUED_UNCERTAIN,
    SPI_FLASH_PROGRAM_COMPLETED,
} spi_flash_program_result_t;

void     spi_flash_init(void);
uint16_t spi_flash_read_id(void);
bool     spi_flash_read(uint32_t addr, uint8_t *buf, uint32_t len);
bool     spi_flash_write(uint32_t addr, const uint8_t *buf, uint32_t len);
spi_flash_program_result_t spi_flash_write_result(
    uint32_t addr, const uint8_t *buf, uint32_t len);
bool     spi_flash_erase_sector(uint32_t addr);
bool     spi_flash_erase_chip(void);

#endif
