#ifndef FOTA_H
#define FOTA_H

#include <stdint.h>
#include <stdbool.h>
#include "ext_flash_layout.h"

/*
 * FOTA flash layout on BY25Q16:
 *   Download buffer: 0x010000 – 0x10FFFF (1 MB)
 *
 * Flow:
 *   1. HTTP GET firmware URL → stream to SPI flash @ FOTA_FLASH_ADDR
 *   2. Verify CRC32 of downloaded image
 *   3. Mark flash slot as "pending upgrade"
 *   4. NVIC_SystemReset() → bootloader picks up and programs MCU flash
 *
 * NOTE: This implementation stores the upgrade image in SPI flash.
 * The MCU-side bootloader at 0x08000000–0x08003FFF is responsible for
 * copying from SPI flash to internal flash on next boot.
 */

#define FOTA_FLASH_ADDR   EXT_FLASH_CANDIDATE_ADDR
#define FOTA_MAX_SIZE     EXT_FLASH_CANDIDATE_SIZE
#define FOTA_PENDING_ADDR EXT_FLASH_RESUME_ADDR
#define FOTA_PENDING_MAGIC 0xF07AF07AUL

typedef enum {
    FOTA_STATE_IDLE = 0,
    FOTA_STATE_CONNECTING,
    FOTA_STATE_DOWNLOADING,
    FOTA_STATE_VERIFYING,
    FOTA_STATE_READY,    /* download OK, waiting for reboot */
    FOTA_STATE_ERROR,
} fota_state_t;

void        fota_init(void);
void        fota_process(void);                  /* call from main loop */
int         fota_start(const char *url);         /* kick off download */
fota_state_t fota_get_state(void);
uint32_t    fota_get_progress(void);             /* bytes downloaded */
void        fota_apply(void);                    /* mark pending + reboot */

/* Called by EC800M HTTP data callback */
void fota_on_data(const uint8_t *data, uint16_t len);
void fota_on_http_header(const char *header);    /* parse Content-Length */

#endif
