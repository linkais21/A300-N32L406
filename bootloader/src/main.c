#include "image_install.h"
#include "bcr.h"
#include "platform_n32l406.h"
int main(void) {
    if (!boot_platform_init()) {
        for (;;) { boot_recovery_step(); boot_watchdog_feed(); }
    }
    if (!bcr_note_trial_reset(boot_reset_was_fault_or_watchdog())) {
        for (;;) { boot_recovery_step(); boot_watchdog_feed(); }
    }
    (void)bootloader_select_image();
    for (;;) { boot_recovery_step(); boot_watchdog_feed(); }
}
