# OTA progress diagnostics

User requests log analysis, download/install progress, and one version per future delivery (same-version SWD + OTA). Formal release status continues to require gates; do not fabricate acceptance.

Log confirms V3044 to V3045 success, 20 download progress lines, authorized/pending/reboot, trial confirmation reboot consistent with source. First 401 recovered to 200 in later boot. Healthy samples F=0, gap4136; QDROP only, stable after startup. Do not claim complete stack or long-soak acceptance.

Implementation: retain bounded 5% download reports; add initial/resumed byte progress; label candidate erase as preparation (not actual installation). Add an explicitly linked install progress function to boot image installation, called after page verification and durable BCR commit, throttled to 10% buckets and final completion only after TRIAL commit. Hardware implementation uses existing PA9 AF4 USART1,115200 TX, bounded polling, watchdog service and no heap/printf. UART failure disables output for that boot but does not fail or hang installation. Old bootloader cannot gain progress via App-only OTA.

Tests: actual install_resume with fake flash/BCR failure cases, completion ordering, resume offsets and throttling; UART output stalls bounded; production FOTA progress log capture; existing Boot/FOTA regressions. Build App and Boot in isolated directories, preserve release gate failure if incomplete. Do not package two versions or overwrite archived firmware.
