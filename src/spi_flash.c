#include "spi_flash.h"
#include "config.h"
#include "debug_uart.h"
#include "hw_init.h"
#include "n32l40x.h"
#include <stddef.h>

#define CMD_READ_ID       0x9FU
#define CMD_READ          0x03U
#define CMD_WRITE_ENABLE  0x06U
#define CMD_PAGE_PROGRAM  0x02U
#define CMD_SECTOR_ERASE  0x20U
#define CMD_READ_SR1      0x05U
#define CMD_READ_SR2      0x35U
#define CMD_READ_SR3      0x15U
#define SR_WIP            0x01U
#define SR_WEL            0x02U
#define SR1_BP_MASK       0x7CU
#define SR2_CMP           0x40U
#define EXPECTED_JEDEC_ID 0x684015UL

static bool s_id_checked;
static bool s_id_valid;
static spi_flash_diagnostics_t s_diag;

static void set_failure(spi_flash_failure_t failure) { s_diag.failure = failure; }

static bool xfer_tracked(uint8_t tx, uint8_t *rx, bool *transmitted)
{
    uint32_t start = TICK_MS();
    uint32_t guard = SPI_FLASH_TIMEOUT_MS * 1024U + 1U;
    if (transmitted != NULL) *transmitted = false;
    while (SPI_I2S_GetStatus(FLASH_SPI, SPI_I2S_TE_FLAG) == RESET) {
        if ((uint32_t)(TICK_MS() - start) >= SPI_FLASH_TIMEOUT_MS || guard-- == 0U) return false;
    }
    SPI_I2S_TransmitData(FLASH_SPI, tx);
    if (transmitted != NULL) *transmitted = true;
    start = TICK_MS();
    guard = SPI_FLASH_TIMEOUT_MS * 1024U + 1U;
    while (SPI_I2S_GetStatus(FLASH_SPI, SPI_I2S_RNE_FLAG) == RESET) {
        if ((uint32_t)(TICK_MS() - start) >= SPI_FLASH_TIMEOUT_MS || guard-- == 0U) return false;
    }
    *rx = (uint8_t)SPI_I2S_ReceiveData(FLASH_SPI);
    return true;
}

static bool xfer(uint8_t tx, uint8_t *rx) { return xfer_tracked(tx, rx, NULL); }

static uint32_t raw_id(void)
{
    uint8_t d, m, t, c;
    bool ok;
    FLASH_CS_LOW();
    ok = xfer(CMD_READ_ID, &d) && xfer(0xFFU, &m) && xfer(0xFFU, &t) && xfer(0xFFU, &c);
    FLASH_CS_HIGH();
    return ok ? ((uint32_t)m << 16U) | ((uint32_t)t << 8U) | c : 0U;
}

static bool read_status_command(uint8_t command, uint8_t *value)
{
    uint8_t d;
    bool ok;
    FLASH_CS_LOW();
    ok = xfer(command, &d) && xfer(0xFFU, value);
    FLASH_CS_HIGH();
    return ok;
}

static bool refresh_status(void)
{
    if (!read_status_command(CMD_READ_SR1, &s_diag.status1) ||
        !read_status_command(CMD_READ_SR2, &s_diag.status2) ||
        !read_status_command(CMD_READ_SR3, &s_diag.status3)) {
        set_failure(SPI_FLASH_FAILURE_READY);
        return false;
    }
    return true;
}

static bool protected_status(void)
{
    return (s_diag.status1 & SR1_BP_MASK) != 0U || (s_diag.status2 & SR2_CMP) != 0U;
}

static bool ensure_id(void)
{
    if (!s_id_checked) {
        s_diag.jedec_id = raw_id();
        s_id_valid = s_diag.jedec_id == EXPECTED_JEDEC_ID;
        s_id_checked = true;
        if (!s_id_valid) set_failure(SPI_FLASH_FAILURE_ID);
    }
    return s_id_valid;
}

static bool ready(uint32_t timeout_ms)
{
    uint32_t start = TICK_MS();
    uint32_t guard = timeout_ms * 1024U + 1U;
    do {
        if (!read_status_command(CMD_READ_SR1, &s_diag.status1)) {
            set_failure(SPI_FLASH_FAILURE_READY);
            return false;
        }
        if ((s_diag.status1 & SR_WIP) == 0U) return true;
    } while ((uint32_t)(TICK_MS() - start) < timeout_ms && guard-- != 0U);
    set_failure(SPI_FLASH_FAILURE_READY);
    return false;
}

static bool write_enable(void)
{
    uint8_t d;
    bool ok;
    FLASH_CS_LOW();
    ok = xfer(CMD_WRITE_ENABLE, &d);
    FLASH_CS_HIGH();
    if (!ok || !read_status_command(CMD_READ_SR1, &s_diag.status1) ||
        (s_diag.status1 & SR_WEL) == 0U) {
        (void)refresh_status();
        set_failure(protected_status() ? SPI_FLASH_FAILURE_PROTECTED : SPI_FLASH_FAILURE_WREN);
        return false;
    }
    return true;
}

void spi_flash_init(void)
{
    FLASH_CS_HIGH();
    delay_ms(1U);
    s_id_checked = false;
    s_id_valid = false;
    s_diag = (spi_flash_diagnostics_t){0};
    if (!ensure_id()) {
        dbg_printf("[FLASH] init fail stage=ID JEDEC=%06lX\r\n", (unsigned long)s_diag.jedec_id);
        return;
    }
    if (!refresh_status()) {
        dbg_printf("[FLASH] init fail stage=READY JEDEC=%06lX\r\n", (unsigned long)s_diag.jedec_id);
        return;
    }
    set_failure(SPI_FLASH_FAILURE_NONE);
    dbg_printf("[FLASH] JEDEC=%06lX SR1=%02X SR2=%02X SR3=%02X\r\n",
               (unsigned long)s_diag.jedec_id, s_diag.status1, s_diag.status2, s_diag.status3);
}

uint16_t spi_flash_read_id(void)
{
    s_diag.jedec_id = raw_id();
    s_id_checked = true;
    s_id_valid = s_diag.jedec_id == EXPECTED_JEDEC_ID;
    if (!s_id_valid) set_failure(SPI_FLASH_FAILURE_ID);
    return (uint16_t)(s_diag.jedec_id >> 8U);
}

bool spi_flash_read(uint32_t addr, uint8_t *buf, uint32_t len)
{
    uint8_t d;
    bool ok;
    uint32_t i;
    if (buf == NULL || addr > FLASH_TOTAL_SIZE || len > FLASH_TOTAL_SIZE - addr ||
        !ensure_id() || !ready(SPI_FLASH_TIMEOUT_MS)) return false;
    FLASH_CS_LOW();
    ok = xfer(CMD_READ, &d) && xfer((uint8_t)(addr >> 16U), &d) &&
         xfer((uint8_t)(addr >> 8U), &d) && xfer((uint8_t)addr, &d);
    for (i = 0U; ok && i < len; ++i) ok = xfer(0xFFU, &buf[i]);
    FLASH_CS_HIGH();
    return ok;
}

bool spi_flash_erase_sector(uint32_t addr)
{
    uint8_t d;
    bool ok;
    if (addr >= FLASH_TOTAL_SIZE || addr % FLASH_SECTOR_SIZE != 0U ||
        !ensure_id() || !write_enable()) return false;
    FLASH_CS_LOW();
    ok = xfer(CMD_SECTOR_ERASE, &d) && xfer((uint8_t)(addr >> 16U), &d) &&
         xfer((uint8_t)(addr >> 8U), &d) && xfer((uint8_t)addr, &d);
    FLASH_CS_HIGH();
    if (!ok || !ready(SPI_FLASH_ERASE_TIMEOUT_MS)) {
        (void)refresh_status();
        set_failure(protected_status() ? SPI_FLASH_FAILURE_PROTECTED : SPI_FLASH_FAILURE_ERASE);
        return false;
    }
    set_failure(SPI_FLASH_FAILURE_NONE);
    return true;
}

spi_flash_program_result_t spi_flash_write_result(uint32_t addr, const uint8_t *buf, uint32_t len)
{
    bool issued = false;
    if (buf == NULL || addr > FLASH_TOTAL_SIZE || len > FLASH_TOTAL_SIZE - addr || !ensure_id()) {
        set_failure(SPI_FLASH_FAILURE_PROGRAM);
        return SPI_FLASH_PROGRAM_NOT_ISSUED;
    }
    while (len != 0U) {
        uint32_t chunk = FLASH_PAGE_SIZE - addr % FLASH_PAGE_SIZE;
        uint32_t i;
        uint8_t d;
        bool opcode_sent = false;
        bool ok;
        if (chunk > len) chunk = len;
        if (!write_enable()) return issued ? SPI_FLASH_PROGRAM_ISSUED_UNCERTAIN : SPI_FLASH_PROGRAM_NOT_ISSUED;
        FLASH_CS_LOW();
        ok = xfer_tracked(CMD_PAGE_PROGRAM, &d, &opcode_sent);
        issued = issued || opcode_sent;
        ok = ok && xfer((uint8_t)(addr >> 16U), &d) && xfer((uint8_t)(addr >> 8U), &d) && xfer((uint8_t)addr, &d);
        for (i = 0U; ok && i < chunk; ++i) ok = xfer(buf[i], &d);
        FLASH_CS_HIGH();
        if (!ok || !ready(SPI_FLASH_TIMEOUT_MS)) {
            (void)refresh_status();
            set_failure(protected_status() ? SPI_FLASH_FAILURE_PROTECTED : SPI_FLASH_FAILURE_PROGRAM);
            return issued ? SPI_FLASH_PROGRAM_ISSUED_UNCERTAIN : SPI_FLASH_PROGRAM_NOT_ISSUED;
        }
        addr += chunk;
        buf += chunk;
        len -= chunk;
    }
    set_failure(SPI_FLASH_FAILURE_NONE);
    return SPI_FLASH_PROGRAM_COMPLETED;
}

bool spi_flash_write(uint32_t addr, const uint8_t *buf, uint32_t len)
{
    return spi_flash_write_result(addr, buf, len) == SPI_FLASH_PROGRAM_COMPLETED;
}

void spi_flash_get_diagnostics(spi_flash_diagnostics_t *out) { if (out != NULL) *out = s_diag; }

const char *spi_flash_failure_name(spi_flash_failure_t failure)
{
    switch (failure) {
    case SPI_FLASH_FAILURE_NONE: return "NONE";
    case SPI_FLASH_FAILURE_ID: return "ID";
    case SPI_FLASH_FAILURE_READY: return "READY";
    case SPI_FLASH_FAILURE_WREN: return "WREN";
    case SPI_FLASH_FAILURE_PROTECTED: return "PROTECTED";
    case SPI_FLASH_FAILURE_ERASE: return "ERASE";
    case SPI_FLASH_FAILURE_PROGRAM: return "PROGRAM";
    case SPI_FLASH_FAILURE_VERIFY: return "VERIFY";
    default: return "UNKNOWN";
    }
}

void spi_flash_note_verify_failure(void)
{
    if (refresh_status() && protected_status())
        set_failure(SPI_FLASH_FAILURE_PROTECTED);
    else
        set_failure(SPI_FLASH_FAILURE_VERIFY);
}
