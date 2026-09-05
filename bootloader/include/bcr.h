#ifndef A300_BOOTLOADER_BCR_H
#define A300_BOOTLOADER_BCR_H

#include <stdint.h>
#include <stdbool.h>
#include "boot_contract.h"

bool bcr_load(bcr_record_t *out);
bool bcr_commit(const bcr_record_t *record);
bool bcr_valid(const bcr_record_t *record);
void bcr_note_trial_reset(bool fault_or_watchdog);
bool bcr_mark_trial_healthy(void);
bool boot_bcr_read(uint32_t address, void *data, uint32_t length);
bool boot_bcr_write(uint32_t address, const void *data, uint32_t length);
bool boot_bcr_erase(uint32_t address);
bool boot_bcr_readback(uint32_t address, const void *data, uint32_t length);

#endif
