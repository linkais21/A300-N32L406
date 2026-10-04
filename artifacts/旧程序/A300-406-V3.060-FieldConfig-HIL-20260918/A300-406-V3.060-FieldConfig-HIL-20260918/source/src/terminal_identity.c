#include "terminal_identity.h"
#include "ec800m.h"
#include "flash_config.h"
#include <stddef.h>
#include <string.h>

static terminal_identity_result_t s_last_result = TERMINAL_IDENTITY_INVALID_ARGUMENT;

static bool exact_decimal_text(const char *text, size_t length)
{
    size_t i;
    for (i = 0U; i < length; ++i) {
        if (text[i] == '\0' || text[i] < '0' || text[i] > '9') return false;
    }
    return text[length] == '\0';
}

bool terminal_id_derive(const char *pid, const char *imei, char out[8])
{
    const char *source;

    if (out == NULL) return false;
    out[0] = '\0';
    if (pid == NULL || imei == NULL) return false;

    if (pid[0] != '\0') {
        source = pid;
        if (!exact_decimal_text(source, 11U)) return false;
    } else {
        source = imei;
        if (!exact_decimal_text(source, 15U)) return false;
        source += 4U;
    }

    memcpy(out, source + 4U, 7U);
    out[7] = '\0';
    return true;
}

terminal_identity_result_t terminal_identity_sync_result(
    char pid[12], char phone[13], char terminal_id[8], bool *derived)
{
    device_config_t *config;
    char imei[16] = {0};
    char derived_pid[12];
    terminal_identity_result_t result = TERMINAL_IDENTITY_OK_CONFIG;
    cfg_store_result_t stored;

    if (derived != NULL) *derived = false;
    if (pid == NULL || phone == NULL || terminal_id == NULL)
        return TERMINAL_IDENTITY_INVALID_ARGUMENT;
    pid[0] = '\0';
    phone[0] = '\0';
    terminal_id[0] = '\0';
    config = cfg_get();
    if (config == NULL) return TERMINAL_IDENTITY_INVALID_ARGUMENT;

    if (config->pid[0] != '\0') {
        if (!exact_decimal_text(config->pid, 11U))
            return TERMINAL_IDENTITY_PID_FORMAT;
    } else {
        ec800m_get_imei(imei, sizeof(imei));
        if (!exact_decimal_text(imei, 15U))
            return TERMINAL_IDENTITY_IMEI_FORMAT;
        memcpy(derived_pid, imei + 4U, 11U);
        derived_pid[11] = '\0';
        stored = cfg_set_pid_result(derived_pid);
        if (stored == CFG_STORE_LOCK_FAILED) return TERMINAL_IDENTITY_FLASH_LOCK;
        if (stored == CFG_STORE_WRITE_FAILED) return TERMINAL_IDENTITY_FLASH_WRITE;
        if (stored != CFG_STORE_OK) return TERMINAL_IDENTITY_VERIFY;
        config = cfg_get();
        if (config == NULL || !exact_decimal_text(config->pid, 11U) ||
            memcmp(config->pid, derived_pid, 12U) != 0)
            return TERMINAL_IDENTITY_VERIFY;
        result = TERMINAL_IDENTITY_OK_DERIVED;
        if (derived != NULL) *derived = true;
    }

    memcpy(pid, config->pid, 12U);
    phone[0] = '0';
    memcpy(phone + 1U, pid, 11U);
    phone[12] = '\0';
    memcpy(terminal_id, pid + 4U, 7U);
    terminal_id[7] = '\0';
    return result;
}

bool terminal_identity_sync(char pid[12], char phone[13], char terminal_id[8])
{
    s_last_result = terminal_identity_sync_result(pid, phone, terminal_id, NULL);
    return s_last_result == TERMINAL_IDENTITY_OK_CONFIG ||
           s_last_result == TERMINAL_IDENTITY_OK_DERIVED;
}

terminal_identity_result_t terminal_identity_last_result(void)
{
    return s_last_result;
}

const char *terminal_identity_result_name(terminal_identity_result_t result)
{
    switch (result) {
    case TERMINAL_IDENTITY_OK_CONFIG: return "CONFIG";
    case TERMINAL_IDENTITY_OK_DERIVED: return "IMEI";
    case TERMINAL_IDENTITY_PID_FORMAT: return "PID_FORMAT";
    case TERMINAL_IDENTITY_IMEI_FORMAT: return "IMEI_FORMAT";
    case TERMINAL_IDENTITY_FLASH_LOCK: return "FLASH_LOCK";
    case TERMINAL_IDENTITY_FLASH_WRITE: return "FLASH_WRITE";
    case TERMINAL_IDENTITY_VERIFY: return "VERIFY";
    default: return "ARGUMENT";
    }
}

bool terminal_identity_encode_phone(const char pid[12], uint8_t bcd[6])
{
    uint8_t i;

    if (pid == NULL || bcd == NULL || !exact_decimal_text(pid, 11U))
        return false;
    for (i = 0U; i < 6U; ++i) {
        const uint8_t high = i == 0U ? 0U : (uint8_t)(pid[i * 2U - 1U] - '0');
        const uint8_t low = (uint8_t)(pid[i * 2U] - '0');
        bcd[i] = (uint8_t)((high << 4U) | low);
    }
    return true;
}

bool terminal_identity_load(char out[8])
{
    char pid[12];
    char phone[13];
    return terminal_identity_sync(pid, phone, out);
}
