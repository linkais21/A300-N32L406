#ifndef A300_BOOTLOADER_PLATFORM_N32L406_H
#define A300_BOOTLOADER_PLATFORM_N32L406_H

#include <stdbool.h>
#include <stdint.h>

bool boot_platform_init(void);
bool boot_reset_was_fault_or_watchdog(void);
void boot_recovery_step(void);

#endif
