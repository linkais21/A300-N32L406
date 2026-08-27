#include "spi_flash.h"
#include "config.h"
#include "hw_init.h"
#include "n32l40x.h"

#define CMD_READ_ID 0x9F
#define CMD_READ 0x03
#define CMD_WRITE_ENABLE 0x06
#define CMD_PAGE_PROGRAM 0x02
#define CMD_SECTOR_ERASE 0x20
#define CMD_CHIP_ERASE 0xC7
#define CMD_READ_SR 0x05
#define SR_WIP 0x01
#define SR_WEL 0x02

static bool g_flash_id_checked;
static bool g_flash_id_valid;

static bool expired(uint32_t start) { return (uint32_t)(TICK_MS() - start) >= SPI_FLASH_TIMEOUT_MS; }
static bool spi_xfer(uint8_t tx, uint8_t *rx)
{
    uint32_t start = TICK_MS();
    uint32_t guard = SPI_FLASH_TIMEOUT_MS * 1024U + 1U;
    while (SPI_I2S_GetStatus(FLASH_SPI, SPI_I2S_TE_FLAG) == RESET) {
        if (expired(start) || guard-- == 0U) return false;
    }
    SPI_I2S_TransmitData(FLASH_SPI, tx);
    start = TICK_MS();
    guard = SPI_FLASH_TIMEOUT_MS * 1024U + 1U;
    while (SPI_I2S_GetStatus(FLASH_SPI, SPI_I2S_RNE_FLAG) == RESET) {
        if (expired(start) || guard-- == 0U) return false;
    }
    *rx = (uint8_t)SPI_I2S_ReceiveData(FLASH_SPI);
    return true;
}
static uint16_t read_id_raw(void)
{
    uint8_t d, mfr, type; FLASH_CS_LOW();
    bool ok = spi_xfer(CMD_READ_ID, &d) && spi_xfer(0xFF, &mfr) && spi_xfer(0xFF, &type);
    FLASH_CS_HIGH(); return ok ? (uint16_t)(((uint16_t)mfr << 8) | type) : 0;
}
static bool ensure_flash_id(void)
{
    if (!g_flash_id_checked) { uint16_t id = read_id_raw(); g_flash_id_valid = id != 0 && id != 0xFFFFU; g_flash_id_checked = true; }
    return g_flash_id_valid;
}
static bool read_status(uint8_t *status)
{
    uint8_t d; FLASH_CS_LOW();
    bool ok = spi_xfer(CMD_READ_SR, &d) && spi_xfer(0xFF, status);
    FLASH_CS_HIGH(); return ok;
}
static bool wait_ready(void)
{
    uint32_t start = TICK_MS(); uint32_t guard = SPI_FLASH_TIMEOUT_MS * 1024U + 1U; uint8_t sr;
    do { if (!read_status(&sr)) return false; if (!(sr & SR_WIP)) return true; } while (!expired(start) && guard-- != 0U);
    return false;
}
static bool write_enable(void)
{
    uint8_t d; FLASH_CS_LOW(); bool ok = spi_xfer(CMD_WRITE_ENABLE, &d); FLASH_CS_HIGH();
    if (!ok || !read_status(&d)) return false; return (d & SR_WEL) != 0;
}
void spi_flash_init(void) { g_flash_id_checked = false; (void)ensure_flash_id(); }
uint16_t spi_flash_read_id(void)
{
    uint16_t id = read_id_raw(); g_flash_id_checked = true; g_flash_id_valid = id != 0 && id != 0xFFFFU; return id;
}
bool spi_flash_read(uint32_t addr, uint8_t *buf, uint32_t len)
{
    if (!buf || addr > FLASH_TOTAL_SIZE || len > FLASH_TOTAL_SIZE - addr || !ensure_flash_id()) return false;
    uint8_t d; FLASH_CS_LOW();
    bool ok = spi_xfer(CMD_READ,&d) && spi_xfer((uint8_t)(addr>>16),&d) && spi_xfer((uint8_t)(addr>>8),&d) && spi_xfer((uint8_t)addr,&d);
    for (uint32_t i=0; ok && i<len; ++i) ok = spi_xfer(0xFF,&buf[i]);
    FLASH_CS_HIGH(); return ok;
}
bool spi_flash_erase_sector(uint32_t addr)
{
    if (addr >= FLASH_TOTAL_SIZE || addr % FLASH_SECTOR_SIZE || !ensure_flash_id()) return false;
    if (!write_enable()) return false; uint8_t d; FLASH_CS_LOW();
    bool ok = spi_xfer(CMD_SECTOR_ERASE,&d) && spi_xfer((uint8_t)(addr>>16),&d) && spi_xfer((uint8_t)(addr>>8),&d) && spi_xfer((uint8_t)addr,&d);
    FLASH_CS_HIGH(); return ok && wait_ready();
}
bool spi_flash_write(uint32_t addr, const uint8_t *buf, uint32_t len)
{
    if (!buf || addr > FLASH_TOTAL_SIZE || len > FLASH_TOTAL_SIZE - addr || !ensure_flash_id()) return false;
    while (len) {
        uint32_t n = FLASH_PAGE_SIZE - (addr % FLASH_PAGE_SIZE); if (n > len) n = len;
        if (!write_enable()) return false; uint8_t d; FLASH_CS_LOW();
        bool ok = spi_xfer(CMD_PAGE_PROGRAM,&d) && spi_xfer((uint8_t)(addr>>16),&d) && spi_xfer((uint8_t)(addr>>8),&d) && spi_xfer((uint8_t)addr,&d);
        for (uint32_t i=0; ok && i<n; ++i) ok = spi_xfer(buf[i],&d);
        FLASH_CS_HIGH(); if (!ok || !wait_ready()) return false;
        addr += n; buf += n; len -= n;
    }
    return true;
}
bool spi_flash_erase_chip(void)
{
    if (!ensure_flash_id() || !write_enable()) return false; uint8_t d; FLASH_CS_LOW(); bool ok = spi_xfer(CMD_CHIP_ERASE,&d); FLASH_CS_HIGH(); return ok && wait_ready();
}
