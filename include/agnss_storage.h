#ifndef AGNSS_STORAGE_H
#define AGNSS_STORAGE_H

#include <stdint.h>
#include <stdbool.h>
#include "ext_flash_layout.h"

/* Value 2 is retired; retain its identifier/value for persisted config compatibility. */
typedef enum { GNSS_TYPE_UNKNOWN=0, GNSS_TYPE_TAU804M=1, GNSS_TYPE_ATGM332D_F7N=2 } gnss_type_t;

#define AGNSS_COMMIT_MARKER 0xA66A55AAUL
#define AGNSS_MAX_DATA      (EXT_FLASH_AGNSS_SLOT_SIZE - 256UL)

typedef struct {
    uint32_t magic;
    uint8_t  type;
    uint8_t  reserved[3];
    uint32_t sequence;
    uint32_t length;
    uint32_t timestamp;
    uint32_t crc32;
    uint8_t  sha256[32];
    uint32_t metadata_crc;
    uint32_t commit_marker;
} agnss_meta_t;

bool agnss_storage_init(void);
bool agnss_storage_begin(uint8_t slot);
bool agnss_storage_write(const void *data, uint16_t len);
bool agnss_storage_commit(const agnss_meta_t *meta);
bool agnss_storage_read(uint32_t offset, void *buf, uint16_t len);
bool agnss_storage_get_latest(agnss_meta_t *meta);
void agnss_storage_abort(void);
/* Single-main-loop injection session. Open verifies once and pins a slot;
 * subsequent opens return that snapshot. All AGNSS mutations must use this
 * module's APIs, which invalidate the session before changing flash.
 * Chunk reads check the pinned metadata and release all owners before return.
 * Close at completion/cancellation; any chunk failure also closes the session.
 * Legacy get_latest/read continue to perform fresh full-payload verification. */
bool agnss_storage_read_open(agnss_meta_t *meta);
bool agnss_storage_read_chunk(uint32_t offset, void *buf, uint16_t len);
void agnss_storage_read_close(void);
/* Shared flash-staging scratch buffer, reused by agnss_manager's read/inject
 * loop. Successful read/read_chunk calls finish overwriting it with the
 * requested bytes before returning, and there is only ever one
 * caller (the single-threaded main loop). */
uint8_t *agnss_storage_scratch(uint16_t *capacity);

#endif
