#ifndef A300_BOOT_CONTRACT_H
#define A300_BOOT_CONTRACT_H

#include <stdint.h>

#define BCR_MAGIC 0x42435231UL
#define BCR_COMMIT_MARKER 0x434F4D4DUL
#define BCR_SLOT_A_ADDR 0x100000UL
#define BCR_SLOT_B_ADDR 0x101000UL
#define FOTA_AUTH_SLOT_A_ADDR 0x104000UL
#define FOTA_AUTH_SLOT_B_ADDR 0x105000UL
#define FOTA_LKG_AUTH_ADDR 0x0FF000UL
#define FOTA_FACTORY_AUTH_ADDR 0x0BF000UL
#define LKG_SLOT_A_BASE 0x0C0000UL
#define LKG_SLOT_B_BASE 0x0DB000UL
#define LKG_SLOT_SIZE 0x1B000UL
#define LKG_SLOT_B_AUTH_ADDR 0x0F6000UL
#define LKG_SLOT_A_AUTH_ADDR 0x0FF000UL
#define FOTA_AUTH_MAGIC 0x41555448UL
#define FOTA_AUTH_FORMAT 1U
#define FOTA_AUTH_COMMIT_MARKER 0x41555443UL

typedef enum {
    BCR_ACTIVE = 1,
    BCR_TRIAL = 2,
    BCR_PENDING = 3,
    BCR_ROLLBACK = 4,
    BCR_RECOVERY = 5
} bcr_state_t;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint32_t sequence;
    uint8_t state;
    uint8_t boot_attempts;
    uint16_t reserved;
    uint32_t image_version;
    uint32_t transaction_offset;
    uint32_t transaction_length;
    uint32_t target_address;
    uint32_t rollback_floor;
    uint32_t crc32;
    uint32_t commit_marker;
} bcr_record_t;

_Static_assert(sizeof(bcr_record_t) == 40U, "BCR wire size changed");

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint32_t format_version;
    uint32_t record_length;
    uint32_t sequence;
    uint32_t package_length;
    uint32_t package_version;
    uint32_t target_address;
    uint32_t package_crc32;
    uint32_t signing_key_id;
    uint8_t package_sha256[32];
    uint8_t signature[64];
    uint32_t crc32;
    uint32_t commit_marker;
} fota_authorization_t;

_Static_assert(sizeof(fota_authorization_t) == 140U,
               "FOTA authorization wire size changed");
_Static_assert(LKG_SLOT_A_BASE + LKG_SLOT_SIZE == LKG_SLOT_B_BASE,
               "LKG package slots must be contiguous");
_Static_assert(LKG_SLOT_B_BASE + LKG_SLOT_SIZE == LKG_SLOT_B_AUTH_ADDR,
               "LKG slot B overlaps its authorization");
_Static_assert(LKG_SLOT_B_AUTH_ADDR + 0x1000UL <= LKG_SLOT_A_AUTH_ADDR,
               "LKG authorization sectors overlap");
_Static_assert(LKG_SLOT_A_AUTH_ADDR + 0x1000UL == 0x100000UL,
               "LKG layout exceeds its region");

#endif
