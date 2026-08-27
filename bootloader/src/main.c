#include "image_install.h"
#include "bcr.h"
__attribute__((weak)) bool boot_reset_was_fault_or_watchdog(void) { return false; }
__attribute__((weak)) void boot_recovery_step(void) {}
int main(void) {
    bcr_note_trial_reset(boot_reset_was_fault_or_watchdog());
    if (bootloader_select_image()) return 0;
    for (unsigned i=0; i<1024U; ++i) { boot_recovery_step(); boot_watchdog_feed(); }
    return 0;
}
