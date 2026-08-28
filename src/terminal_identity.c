#include "terminal_identity.h"
#include "ec800m.h"
#include "flash_config.h"
#include <stddef.h>
#include <string.h>

static bool exact_decimal_text(const char *text, size_t length)
{
    size_t i;
    for (i = 0U; i < length; ++i) {
        if (text[i] == '\0' || text[i] < '0' || text[i] > '9') return false;
    }
    return text[length] == '\0';
}

static size_t bounded_decimal_length(const char *text, size_t maximum)
{
    size_t length;
    for (length = 0U; length <= maximum; ++length) {
        if (text[length] == '\0') return length;
        if (text[length] < '0' || text[length] > '9') return maximum + 1U;
    }
    return maximum + 1U;
}

bool terminal_id_derive(const char *pid, const char *imei, char out[8])
{
    const char *source;
    size_t length;

    if (out == NULL) return false;
    out[0] = '\0';
    if (pid == NULL || imei == NULL) return false;

    if (pid[0] != '\0') {
        source = pid;
        length = 11U;
        if (!exact_decimal_text(source, length)) return false;
    } else {
        source = imei;
        length = bounded_decimal_length(source, 15U);
        if (length < 7U || length > 15U) return false;
    }

    memcpy(out, source + length - 7U, 7U);
    out[7] = '\0';
    return true;
}

bool terminal_identity_load(char out[8])
{
    device_config_t *config;
    char imei[16] = {0};

    if (out == NULL) return false;
    out[0] = '\0';
    config = cfg_get();
    if (config == NULL) return false;
    ec800m_get_imei(imei, sizeof(imei));
    return terminal_id_derive(config->pid, imei, out);
}
