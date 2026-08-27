#ifndef FOTA_H
#define FOTA_H

#include <stdint.h>
#include <stdbool.h>
#include "ext_flash_layout.h"

#define FOTA_FLASH_ADDR   EXT_FLASH_CANDIDATE_ADDR
#define FOTA_MAX_SIZE     EXT_FLASH_CANDIDATE_SIZE
#define FOTA_PENDING_ADDR EXT_FLASH_RESUME_ADDR
#define FOTA_PENDING_MAGIC 0xF07AF07AUL
#define FOTA_RESUME_MAGIC 0x46525331UL

typedef struct {
    const char *url;
    uint32_t expected_length;
    const char *etag;
    uint32_t version;
} fota_request_t;

typedef enum {
    FOTA_STATE_IDLE = 0,
    FOTA_STATE_CONNECTING,
    FOTA_STATE_DOWNLOADING,
    FOTA_STATE_VERIFYING,
    FOTA_STATE_READY,
    FOTA_STATE_ERROR,
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
int  fota_start_request(const fota_request_t *req);
int  fota_start(const char *url);
void fota_get_status(fota_status_t *out);
fota_state_t fota_get_state(void);
uint32_t fota_get_progress(void);
void fota_cancel(void);
void fota_apply(void);

void fota_on_chunk(const uint8_t *data, uint16_t len, uint32_t offset);
void fota_on_data(const uint8_t *data, uint16_t len);
void fota_on_http_header(const char *header);

bool fota_verify_manifest(const void *manifest, uint32_t length);
bool fota_bcr_commit_pending(uint32_t version, uint32_t length, uint32_t target);

#endif
