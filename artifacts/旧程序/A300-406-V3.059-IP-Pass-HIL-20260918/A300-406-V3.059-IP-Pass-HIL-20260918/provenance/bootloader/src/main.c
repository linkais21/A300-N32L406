#include "image_install.h"
#include "bcr.h"
#include "platform_n32l406.h"
#include "factory_init.h"
#include "build_version.h"
int main(void) {
    if (!boot_platform_init()) {
        for (;;) { boot_recovery_step(); boot_watchdog_feed(); }
    }
    boot_startup_status("start", FW_VERSION_COUNTER);
    if (factory_init_apply(factory_init_request()) == FACTORY_INIT_RESULT_ERROR) {
        boot_startup_status("factory-error", -1);
        for (;;) { boot_recovery_step(); boot_watchdog_feed(); }
    }
    boot_startup_status("factory-ready", 0);
    if (!bcr_note_trial_reset(boot_reset_was_fault_or_watchdog())) {
        boot_startup_status("reset-record-error", -1);
        for (;;) { boot_recovery_step(); boot_watchdog_feed(); }
    }
    boot_startup_status("select", 0);
    (void)bootloader_select_image();
    boot_startup_status("recovery", -1);
    for (;;) { boot_recovery_step(); boot_watchdog_feed(); }
}
