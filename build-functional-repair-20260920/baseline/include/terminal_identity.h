#ifndef TERMINAL_IDENTITY_H
#define TERMINAL_IDENTITY_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    TERMINAL_IDENTITY_OK_CONFIG = 0,
    TERMINAL_IDENTITY_OK_DERIVED,
    TERMINAL_IDENTITY_INVALID_ARGUMENT,
    TERMINAL_IDENTITY_PID_FORMAT,
    TERMINAL_IDENTITY_IMEI_FORMAT,
    TERMINAL_IDENTITY_FLASH_LOCK,
    TERMINAL_IDENTITY_FLASH_WRITE,
    TERMINAL_IDENTITY_VERIFY,
} terminal_identity_result_t;

bool terminal_id_derive(const char *pid, const char *imei, char out[8]);
bool terminal_identity_load(char out[8]);
bool terminal_identity_sync(char pid[12], char phone[13], char terminal_id[8]);
terminal_identity_result_t terminal_identity_sync_result(
    char pid[12], char phone[13], char terminal_id[8], bool *derived);
const char *terminal_identity_result_name(terminal_identity_result_t result);
terminal_identity_result_t terminal_identity_last_result(void);
bool terminal_identity_encode_phone(const char pid[12], uint8_t bcd[6]);

#endif /* TERMINAL_IDENTITY_H */
