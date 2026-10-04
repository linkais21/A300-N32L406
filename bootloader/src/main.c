#include "image_install.h"
#include "image_verify.h"
#include "bcr.h"
#include "platform_n32l406.h"
#include "factory_init.h"
#include "build_version.h"
int main(void) {
    factory_init_result_t factory_result;
    if (!boot_platform_init()) {
        for (;;) { boot_recovery_step(); boot_watchdog_feed(); }
    }
    boot_startup_status("start", FW_VERSION_COUNTER);
    factory_result = factory_init_apply(factory_init_request());
    if (factory_result == FACTORY_INIT_RESULT_DEVICE_UNAVAILABLE &&
        boot_app_vectors_valid(APP_FLASH_BASE)) {
        boot_startup_status("factory-unavailable", -1);
        boot_jump_to(APP_FLASH_BASE);
    }
    if (factory_result < 0) {
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
