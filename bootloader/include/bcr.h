#ifndef A300_BOOTLOADER_BCR_H
#define A300_BOOTLOADER_BCR_H

#include <stdint.h>
#include <stdbool.h>

#define BCR_MAGIC 0x42435231UL /* BCR1 */
#define BCR_COMMIT_MARKER 0x434F4D4DUL /* COMM */
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
    uint32_t crc32;
    uint32_t commit_marker;
} bcr_record_t;

bool bcr_load(bcr_record_t *out);
bool bcr_commit(const bcr_record_t *record);
bool bcr_valid(const bcr_record_t *record);
void bcr_note_trial_reset(bool fault_or_watchdog);
bool bcr_mark_trial_healthy(void);
bool boot_bcr_erase(uint32_t address);
bool boot_bcr_readback(uint32_t address, const void *data, uint32_t length);

#endif
