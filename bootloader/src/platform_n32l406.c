#include "platform_n32l406.h"
#include "bootloader_config.h"
#include "image_install.h"
#include "image_verify.h"
#include "bcr.h"
#include "n32l40x.h"
#include "n32l40x_flash.h"
#include "n32l40x_gpio.h"
#include "n32l40x_iwdg.h"
#include "n32l40x_rcc.h"
#include "n32l40x_spi.h"
#include <stddef.h>
#include <string.h>

#define INTERNAL_PAGE_SIZE     2048UL
#define EXT_TIMEOUT_LOOPS      4000000UL
#define EXT_ERASE_TIMEOUT_LOOPS 32000000UL

#define CMD_READ_ID       0x9FU
#define CMD_READ          0x03U
#define CMD_WRITE_ENABLE  0x06U
#define CMD_PAGE_PROGRAM  0x02U
#define CMD_SECTOR_ERASE  0x20U
#define CMD_READ_STATUS   0x05U
#define STATUS_WIP        0x01U
#define STATUS_WEL        0x02U
#define EXPECTED_JEDEC_ID 0x684015UL

static bool s_fault_reset;

static bool ext_bounds(uint32_t address, uint32_t length)
{
    return length <= FLASH_TOTAL_SIZE && address <= FLASH_TOTAL_SIZE - length;
}

static bool app_bounds(uint32_t address, uint32_t length)
{
    return length <= APP_FLASH_MAX_SIZE && address >= APP_FLASH_BASE &&
           address <= APP_FLASH_END - length;
}

static void cs_high(void) { GPIO_SetBits(GPIOA, GPIO_PIN_4); }
static void cs_low(void) { GPIO_ResetBits(GPIOA, GPIO_PIN_4); }

static bool spi_xfer(uint8_t tx, uint8_t *rx)
{
    uint32_t guard = EXT_TIMEOUT_LOOPS;
    while (SPI_I2S_GetStatus(SPI1, SPI_I2S_TE_FLAG) == RESET) {
        if (guard-- == 0U) return false;
        boot_watchdog_feed();
    }
    SPI_I2S_TransmitData(SPI1, tx);
    guard = EXT_TIMEOUT_LOOPS;
    while (SPI_I2S_GetStatus(SPI1, SPI_I2S_RNE_FLAG) == RESET) {
        if (guard-- == 0U) return false;
        boot_watchdog_feed();
    }
    *rx = (uint8_t)SPI_I2S_ReceiveData(SPI1);
    return true;
}

static bool read_status(uint8_t *status)
{
    uint8_t discard;
    bool ok;
    cs_low();
    ok = spi_xfer(CMD_READ_STATUS, &discard) && spi_xfer(0xFFU, status);
    cs_high();
    return ok;
}

static bool wait_ready(uint32_t guard)
{
    uint8_t status;
    while (guard-- != 0U) {
        if (!read_status(&status)) return false;
        if ((status & STATUS_WIP) == 0U) return true;
        boot_watchdog_feed();
    }
    return false;
}

static bool write_enable(void)
{
    uint8_t discard, status;
    bool ok;
    cs_low();
    ok = spi_xfer(CMD_WRITE_ENABLE, &discard);
    cs_high();
    return ok && read_status(&status) && (status & STATUS_WEL) != 0U;
}

static bool jedec_valid(void)
{
    uint8_t discard, manufacturer, type, capacity;
    bool ok;
    cs_low();
    ok = spi_xfer(CMD_READ_ID, &discard) && spi_xfer(0xFFU, &manufacturer) &&
         spi_xfer(0xFFU, &type) && spi_xfer(0xFFU, &capacity);
    cs_high();
    return ok && ((((uint32_t)manufacturer << 16) |
                   ((uint32_t)type << 8) | capacity) == EXPECTED_JEDEC_ID);
}

bool boot_platform_init(void)
{
    GPIO_InitType gpio;
    SPI_InitType spi;
    s_fault_reset = RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_IWDGRSTF) == SET ||
                    RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_WWDGRSTF) == SET ||
                    RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_LPWRRSTF) == SET;
    /* The reset flags are deliberately left set here.  Reading them is
     * non-destructive, and clearing them at this point made the App report
     * "Reset: unknown" for every boot -- it runs after us and had nothing left
     * to inspect.  reset_diag_capture() in the App clears them instead. */

    RCC_EnableAPB2PeriphClk(RCC_APB2_PERIPH_GPIOA | RCC_APB2_PERIPH_AFIO |
                            RCC_APB2_PERIPH_SPI1, ENABLE);
    GPIO_InitStruct(&gpio);
    gpio.Pin = GPIO_PIN_4;
    gpio.GPIO_Mode = GPIO_Mode_Out_PP;
    gpio.GPIO_Slew_Rate = GPIO_Slew_Rate_High;
    gpio.GPIO_Current = GPIO_DC_12mA;
    gpio.GPIO_Pull = GPIO_No_Pull;
    GPIO_InitPeripheral(GPIOA, &gpio);
    cs_high();

    gpio.Pin = GPIO_PIN_5 | GPIO_PIN_6 | GPIO_PIN_7;
    gpio.GPIO_Mode = GPIO_Mode_AF_PP;
    gpio.GPIO_Current = GPIO_DC_4mA;
    gpio.GPIO_Alternate = GPIO_AF0_SPI1;
    GPIO_InitPeripheral(GPIOA, &gpio);

    SPI_InitStruct(&spi);
    spi.DataDirection = SPI_DIR_DOUBLELINE_FULLDUPLEX;
    spi.SpiMode = SPI_MODE_MASTER;
    spi.DataLen = SPI_DATA_SIZE_8BITS;
    spi.CLKPOL = SPI_CLKPOL_LOW;
    spi.CLKPHA = SPI_CLKPHA_FIRST_EDGE;
    spi.NSS = SPI_NSS_SOFT;
    spi.BaudRatePres = SPI_BR_PRESCALER_4;
    spi.FirstBit = SPI_FB_MSB;
    spi.CRCPoly = 7U;
    SPI_Init(SPI1, &spi);
    SPI_Enable(SPI1, ENABLE);

    IWDG_WriteConfig(IWDG_WRITE_ENABLE);
    IWDG_SetPrescalerDiv(IWDG_PRESCALER_DIV256);
    IWDG_CntReload(0x0FFFU);
    IWDG_ReloadKey();
    IWDG_Enable();
    /* External NOR is needed for BCR/FOTA, but must not prevent a valid App
     * already in internal Flash from booting when the probe is unavailable. */
    (void)jedec_valid();
    return true;
}

bool boot_ext_read(uint32_t address, void *data, uint32_t length)
{
    uint8_t discard, *out = (uint8_t *)data;
    bool ok;
    if ((!data && length != 0U) || !ext_bounds(address, length) ||
        !wait_ready(EXT_TIMEOUT_LOOPS)) return false;
    cs_low();
    ok = spi_xfer(CMD_READ, &discard) && spi_xfer((uint8_t)(address >> 16), &discard) &&
         spi_xfer((uint8_t)(address >> 8), &discard) && spi_xfer((uint8_t)address, &discard);
    for (uint32_t i = 0U; ok && i < length; ++i) ok = spi_xfer(0xFFU, &out[i]);
    cs_high();
    return ok;
}

bool boot_ext_write(uint32_t address, const void *data, uint32_t length)
{
    const uint8_t *in = (const uint8_t *)data;
    uint8_t discard;
    if ((!data && length != 0U) || !ext_bounds(address, length)) return false;
    while (length != 0U) {
        uint32_t chunk = FLASH_PAGE_SIZE - (address % FLASH_PAGE_SIZE);
        if (chunk > length) chunk = length;
        if (!wait_ready(EXT_TIMEOUT_LOOPS) || !write_enable()) return false;
        cs_low();
        bool ok = spi_xfer(CMD_PAGE_PROGRAM, &discard) &&
                  spi_xfer((uint8_t)(address >> 16), &discard) &&
                  spi_xfer((uint8_t)(address >> 8), &discard) &&
                  spi_xfer((uint8_t)address, &discard);
        for (uint32_t i = 0U; ok && i < chunk; ++i) ok = spi_xfer(in[i], &discard);
        cs_high();
        if (!ok || !wait_ready(EXT_TIMEOUT_LOOPS)) return false;
        address += chunk; in += chunk; length -= chunk;
    }
    return true;
}

bool boot_ext_erase(uint32_t address, uint32_t length)
{
    uint8_t discard;
    if (!ext_bounds(address, length) || address % FLASH_SECTOR_SIZE != 0U ||
        length % FLASH_SECTOR_SIZE != 0U) return false;
    while (length != 0U) {
        if (!wait_ready(EXT_TIMEOUT_LOOPS) || !write_enable()) return false;
        cs_low();
        bool ok = spi_xfer(CMD_SECTOR_ERASE, &discard) &&
                  spi_xfer((uint8_t)(address >> 16), &discard) &&
                  spi_xfer((uint8_t)(address >> 8), &discard) &&
                  spi_xfer((uint8_t)address, &discard);
        cs_high();
        if (!ok || !wait_ready(EXT_ERASE_TIMEOUT_LOOPS)) return false;
        address += FLASH_SECTOR_SIZE; length -= FLASH_SECTOR_SIZE;
    }
    return true;
}

bool boot_ext_is_complete(uint32_t address, uint32_t length)
{
    uint8_t buffer[64];
    if (!ext_bounds(address, length)) return false;
    while (length != 0U) {
        uint32_t chunk = length > sizeof buffer ? sizeof buffer : length;
        if (!boot_ext_read(address, buffer, chunk)) return false;
        for (uint32_t i = 0U; i < chunk; ++i) if (buffer[i] != 0xFFU) return true;
        address += chunk; length -= chunk;
    }
    return false;
}

bool boot_int_flash_read(uint32_t address, void *data, uint32_t length)
{
    if ((!data && length != 0U) || !app_bounds(address, length)) return false;
    memcpy(data, (const void *)(uintptr_t)address, length);
    return true;
}

bool boot_int_flash_erase(uint32_t address, uint32_t length)
{
    uint32_t first, end;
    bool ok = true;
    if (length == 0U || !app_bounds(address, length)) return false;
    first = address & ~(INTERNAL_PAGE_SIZE - 1UL);
    end = (address + length + INTERNAL_PAGE_SIZE - 1UL) & ~(INTERNAL_PAGE_SIZE - 1UL);
    if (first < APP_FLASH_BASE || end > APP_FLASH_END) return false;
    FLASH_Unlock();
    for (uint32_t page = first; page < end; page += INTERNAL_PAGE_SIZE) {
        if (FLASH_EraseOnePage(page) != FLASH_COMPL) { ok = false; break; }
        boot_watchdog_feed();
    }
    FLASH_Lock();
    return ok;
}

bool boot_int_flash_program(uint32_t address, const void *data, uint32_t length)
{
    const uint8_t *in = (const uint8_t *)data;
    bool ok = true;
    if (!data || length == 0U || (address & 3U) != 0U ||
        !app_bounds(address, length)) return false;
    FLASH_Unlock();
    for (uint32_t offset = 0U; offset < length; offset += 4U) {
        uint32_t word = 0xFFFFFFFFUL;
        uint32_t chunk = length - offset < sizeof word ? length - offset : sizeof word;
        if (!app_bounds(address + offset, sizeof word)) { ok = false; break; }
        memcpy(&word, in + offset, chunk);
        if (FLASH_ProgramWord(address + offset, word) != FLASH_COMPL ||
            *(const volatile uint32_t *)(uintptr_t)(address + offset) != word) {
            ok = false; break;
        }
        boot_watchdog_feed();
    }
    FLASH_Lock();
    return ok;
}

bool boot_bcr_read(uint32_t address, void *data, uint32_t length)
{
    return boot_ext_read(address, data, length);
}

bool boot_bcr_write(uint32_t address, const void *data, uint32_t length)
{
    return boot_ext_write(address, data, length);
}

bool boot_bcr_erase(uint32_t address)
{
    return boot_ext_erase(address, FLASH_SECTOR_SIZE);
}

bool boot_bcr_readback(uint32_t address, const void *data, uint32_t length)
{
    uint8_t actual[64];
    const uint8_t *expected = (const uint8_t *)data;
    while (length != 0U) {
        uint32_t chunk = length > sizeof actual ? sizeof actual : length;
        if (!boot_ext_read(address, actual, chunk) || memcmp(actual, expected, chunk) != 0) return false;
        address += chunk; expected += chunk; length -= chunk;
    }
    return true;
}

void boot_watchdog_feed(void) { IWDG_ReloadKey(); }
bool boot_reset_was_fault_or_watchdog(void) { return s_fault_reset; }
void boot_recovery_step(void)
{
    /* Keep the core running so the watchdog feed in main() is always reached.
     * A WFI here can sleep forever when no recovery/wake interrupt is pending,
     * causing an IWDG reset loop that prevents SWD from attaching. */
    for (volatile uint32_t spin = 0U; spin < 10000U; ++spin) {
        __NOP();
    }
}

bool boot_rollback_counter(uint32_t *out)
{
    bcr_record_t record;
    if (!out || bcr_load(&record) != BCR_LOAD_FOUND) return false;
    *out = record.rollback_floor;
    return true;
}

void boot_jump_to(uint32_t address)
{
    uint32_t msp, reset;
    if (!boot_app_vectors_valid(address)) return;
    msp = *(const volatile uint32_t *)(uintptr_t)address;
    reset = *(const volatile uint32_t *)(uintptr_t)(address + 4U);
    __disable_irq();
    SysTick->CTRL = 0U;
    SysTick->LOAD = 0U;
    SysTick->VAL = 0U;
    for (uint32_t i = 0U; i < 8U; ++i) {
        NVIC->ICER[i] = 0xFFFFFFFFUL;
        NVIC->ICPR[i] = 0xFFFFFFFFUL;
    }
    SCB->VTOR = address;
    __DSB(); __ISB();
    __set_MSP(msp);
    /* The App starts from reset semantics; do not carry Bootloader PRIMASK. */
    __enable_irq();
    ((void (*)(void))(uintptr_t)reset)();
}

bool boot_app_vectors_valid(uint32_t address)
{
    uint32_t msp, reset;
    if (address != APP_FLASH_BASE) return false;
    msp = *(const volatile uint32_t *)(uintptr_t)address;
    reset = *(const volatile uint32_t *)(uintptr_t)(address + 4U);
    return msp >= 0x20000000UL && msp <= 0x20006000UL && (msp & 7U) == 0U &&
           reset >= APP_FLASH_BASE + 1UL && reset < APP_FLASH_END && (reset & 1U) != 0U;
}

bool boot_compute_internal_hash(uint32_t address, uint32_t length, uint8_t hash[32])
{
    (void)address; (void)length; (void)hash;
    return false;
}
