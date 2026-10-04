#ifndef FOTA_H
#define FOTA_H

#include <stdint.h>
#include <stdbool.h>
#include "ext_flash_layout.h"

#define FOTA_FLASH_ADDR   EXT_FLASH_CANDIDATE_ADDR
#define FOTA_MAX_SIZE     EXT_FLASH_CANDIDATE_SIZE
#define FOTA_PENDING_ADDR EXT_FLASH_RESUME_ADDR
#define FOTA_PENDING_MAGIC 0xF07AF07AUL
#define FOTA_PACKAGE_HEADER_MAGIC 0xA300B007UL
#define FOTA_PACKAGE_HEADER_SIZE 32U
#define FOTA_PACKAGE_PRODUCT_ID 0x41333030UL
#define FOTA_PACKAGE_SIGNATURE_SIZE 64U

typedef struct {
    const char *url;
    uint32_t expected_length;
    const char *etag;
    uint32_t version;
    const uint8_t *package_sha256;
    const uint8_t *signature;
    uint32_t signing_key_id;
} fota_request_t;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint32_t version;
    uint32_t body_size;
    uint32_t body_crc32;
    uint32_t product_id;
    uint8_t reserved[12];
} fota_package_header_t;
_Static_assert(sizeof(fota_package_header_t) == FOTA_PACKAGE_HEADER_SIZE,
               "A300 OTA header wire size must remain 32 bytes");

typedef enum {
    FOTA_STATE_IDLE = 0,
    FOTA_STATE_CONNECTING,
    FOTA_STATE_DOWNLOADING,
    FOTA_STATE_VERIFYING,
    FOTA_STATE_READY,
    FOTA_STATE_ERROR,
    FOTA_STATE_CHECK_CONNECTING,
    FOTA_STATE_CHECKING,
    FOTA_STATE_PREPARING,
} fota_state_t;

typedef struct {
    fota_state_t state;
    uint32_t offset;
    uint32_t expected_length;
    uint32_t crc32;
    uint8_t resumable;
    char url[128];
    char etag[40];
} fota_status_t;

void fota_init(void);
void fota_process(void);
/* Arm an immediate update check; an active transfer finishes first. */
bool fota_request_check(void);
int  fota_start_request(const fota_request_t *req);
/* expected_length must be known and nonzero. PREPARING erases the candidate
 * tail incrementally before CONNECTING; explicit URLs must be same-origin. */
int  fota_start(const char *url);
void fota_get_status(fota_status_t *out);
fota_state_t fota_get_state(void);
/* OTA owns modem/AGNSS scheduling through READY's bounded status exchange.
 * Downloaded images then reset; post-boot success reports return to IDLE.
 * IDLE and ERROR
 * release that ownership. This is not a Flash owner-lock query. */
static inline bool fota_is_active(void)
{
    fota_state_t state = fota_get_state();
    return state == FOTA_STATE_CHECK_CONNECTING || state == FOTA_STATE_CHECKING ||
           state == FOTA_STATE_PREPARING || state == FOTA_STATE_CONNECTING ||
           state == FOTA_STATE_DOWNLOADING || state == FOTA_STATE_VERIFYING ||
           state == FOTA_STATE_READY;
}

uint32_t fota_get_progress(void);
void fota_cancel(void);
/* READY download: install/reset. READY success report: release resources,
 * keep unacknowledged journal for retry; never reboot the confirmed app. */
void fota_apply(void);

void fota_on_chunk(const uint8_t *data, uint16_t len, uint32_t offset);
void fota_on_http_header(const char *header);
#ifdef A300_FIRMWARE_IMAGE
void fota_ec800m_rx(uint8_t ch, const uint8_t *data, uint16_t len);
#endif

bool fota_verify_manifest(const void *manifest, uint32_t length);
bool fota_bcr_commit_pending(uint32_t version, uint32_t length, uint32_t target);
void fota_confirm_trial_process(void);

#endif
