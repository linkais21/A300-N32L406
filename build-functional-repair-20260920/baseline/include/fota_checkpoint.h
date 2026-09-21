#ifndef FOTA_CHECKPOINT_H
#define FOTA_CHECKPOINT_H
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "ext_flash_layout.h"
#include "boot_contract.h"
#define FOTA_CHECKPOINT_SLOT_A (EXT_FLASH_RESUME_ADDR + 0x2000UL)
#define FOTA_CHECKPOINT_SLOT_B (EXT_FLASH_RESUME_ADDR + 0x3000UL)
#define FOTA_CHECKPOINT_MAGIC 0x46524350UL
#define FOTA_CHECKPOINT_FORMAT 1U
#define FOTA_CHECKPOINT_MARKER 0x43485054UL
#define FOTA_AUTH_SLOT_A FOTA_AUTH_SLOT_A_ADDR
#define FOTA_AUTH_SLOT_B FOTA_AUTH_SLOT_B_ADDR
#define FOTA_AUTH_MARKER FOTA_AUTH_COMMIT_MARKER
typedef struct __attribute__((packed)) {
    uint32_t magic, format_version, record_length, sequence;
    uint32_t offset, expected_length, version, running_crc;
    char url[128], etag[40];
    uint32_t crc32, commit_marker;
} fota_checkpoint_t;
_Static_assert(sizeof(fota_checkpoint_t) == 208U, "checkpoint wire size changed");
_Static_assert(FLASH_SECTOR_SIZE == 4096U, "checkpoint requires 4 KiB erase");
_Static_assert(FOTA_CHECKPOINT_SLOT_A >= BCR_SLOT_B_ADDR + FLASH_SECTOR_SIZE,
               "checkpoint overlaps BCR");
_Static_assert(FOTA_CHECKPOINT_SLOT_A % FLASH_SECTOR_SIZE == 0U &&
               FOTA_CHECKPOINT_SLOT_B == FOTA_CHECKPOINT_SLOT_A + FLASH_SECTOR_SIZE &&
               FOTA_CHECKPOINT_SLOT_B + FLASH_SECTOR_SIZE <= FOTA_AUTH_SLOT_A,
               "checkpoint slots outside reserved region");
_Static_assert(FOTA_AUTH_SLOT_A % FLASH_SECTOR_SIZE == 0U &&
               FOTA_AUTH_SLOT_B == FOTA_AUTH_SLOT_A + FLASH_SECTOR_SIZE &&
               FOTA_AUTH_SLOT_B + FLASH_SECTOR_SIZE <= EXT_FLASH_RESUME_ADDR + EXT_FLASH_RESUME_SIZE,
               "authorization slots outside reserved region");
/* Caller holds EXT_FLASH_OWNER_OTA. No lock acquisition or direct SPI access.
 * sequence/format/CRC/marker are assigned by commit; zero length is reserved
 * internally for clear's atomic tombstone, which suppresses older records. */
bool fota_checkpoint_load(const char *url, uint32_t expected_length, fota_checkpoint_t *out);
/* OTA lock required. -1: I/O failure; 0: absent/tombstone; 1: valid record.
 * Used to recover a post-install report without a new download offer. */
int fota_checkpoint_read(fota_checkpoint_t *out);
bool fota_checkpoint_commit(const fota_checkpoint_t *record);
bool fota_checkpoint_clear(void);
bool fota_authorization_load(fota_authorization_t *out);
bool fota_authorization_commit(const fota_authorization_t *record);
bool fota_authorization_clear(void);
#endif
