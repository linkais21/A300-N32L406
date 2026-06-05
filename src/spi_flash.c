#include "spi_flash.h"
#include "config.h"
#include "hw_init.h"
#include "n32l40x.h"

/* BY25Q16 commands */
#define CMD_READ_ID      0x9F
#define CMD_READ         0x03
#define CMD_WRITE_ENABLE 0x06
#define CMD_PAGE_PROGRAM 0x02
#define CMD_SECTOR_ERASE 0x20
#define CMD_CHIP_ERASE   0xC7
#define CMD_READ_SR      0x05
#define SR_WIP           0x01   /* write-in-progress */

static uint8_t spi_xfer(uint8_t tx)
{
    while (SPI_I2S_GetStatus(FLASH_SPI, SPI_I2S_TE_FLAG) == RESET);
    SPI_I2S_TransmitData(FLASH_SPI, tx);
    while (SPI_I2S_GetStatus(FLASH_SPI, SPI_I2S_RNE_FLAG) == RESET);
    return (uint8_t)SPI_I2S_ReceiveData(FLASH_SPI);
}

static void flash_wait_ready(void)
{
    FLASH_CS_LOW();
    spi_xfer(CMD_READ_SR);
    while (spi_xfer(0xFF) & SR_WIP);
    FLASH_CS_HIGH();
}

static void flash_write_enable(void)
{
    FLASH_CS_LOW();
    spi_xfer(CMD_WRITE_ENABLE);
    FLASH_CS_HIGH();
}

void spi_flash_init(void) {}   /* SPI already configured in hw_spi_init */

uint16_t spi_flash_read_id(void)
{
    FLASH_CS_LOW();
    spi_xfer(CMD_READ_ID);
    uint8_t mfr  = spi_xfer(0xFF);
    uint8_t type = spi_xfer(0xFF);
    FLASH_CS_HIGH();
    return ((uint16_t)mfr << 8) | type;
}

void spi_flash_read(uint32_t addr, uint8_t *buf, uint32_t len)
{
    FLASH_CS_LOW();
    spi_xfer(CMD_READ);
    spi_xfer((addr >> 16) & 0xFF);
    spi_xfer((addr >> 8)  & 0xFF);
    spi_xfer(addr & 0xFF);
    for (uint32_t i = 0; i < len; i++) buf[i] = spi_xfer(0xFF);
    FLASH_CS_HIGH();
}

void spi_flash_erase_sector(uint32_t addr)
{
    flash_write_enable();
    FLASH_CS_LOW();
    spi_xfer(CMD_SECTOR_ERASE);
    spi_xfer((addr >> 16) & 0xFF);
    spi_xfer((addr >> 8)  & 0xFF);
    spi_xfer(addr & 0xFF);
    FLASH_CS_HIGH();
    flash_wait_ready();
}

void spi_flash_write(uint32_t addr, const uint8_t *buf, uint32_t len)
{
    while (len > 0) {
        uint32_t page_off   = addr % FLASH_PAGE_SIZE;
        uint32_t chunk      = FLASH_PAGE_SIZE - page_off;
        if (chunk > len) chunk = len;

        flash_write_enable();
        FLASH_CS_LOW();
        spi_xfer(CMD_PAGE_PROGRAM);
        spi_xfer((addr >> 16) & 0xFF);
        spi_xfer((addr >> 8)  & 0xFF);
        spi_xfer(addr & 0xFF);
        for (uint32_t i = 0; i < chunk; i++) spi_xfer(buf[i]);
        FLASH_CS_HIGH();
        flash_wait_ready();

        addr += chunk;
        buf  += chunk;
        len  -= chunk;
    }
}

void spi_flash_erase_chip(void)
{
    flash_write_enable();
    FLASH_CS_LOW();
    spi_xfer(CMD_CHIP_ERASE);
    FLASH_CS_HIGH();
    flash_wait_ready();
}
