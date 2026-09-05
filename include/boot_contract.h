#ifndef A300_BOOT_CONTRACT_H
#define A300_BOOT_CONTRACT_H

#include <stdint.h>

#define BCR_MAGIC 0x42435231UL
#define BCR_COMMIT_MARKER 0x434F4D4DUL
#define BCR_SLOT_A_ADDR 0x100000UL
#define BCR_SLOT_B_ADDR 0x101000UL

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

#endif
