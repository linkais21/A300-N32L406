#include "f39_command.h"

#include <stdbool.h>
#include <string.h>

/* Longest root is seven ASCII bytes; avoid a Flash pointer per entry. */
static const char s_roots[][8] = {
    [F39_OPERATION_PARAM] = "PARAM",
    [F39_OPERATION_DUALSET] = "DUALSET",
    [F39_OPERATION_RESET] = "RESET",
    [F39_OPERATION_PID] = "PID",
    [F39_OPERATION_IP] = "IP",
    [F39_OPERATION_FIP] = "FIP",
    [F39_OPERATION_FREQ] = "FREQ",
    [F39_OPERATION_HBT] = "HBT",
    [F39_OPERATION_MODEL] = "MODEL",
    [F39_OPERATION_SPEED] = "SPEED",
    [F39_OPERATION_APN] = "APN",
    [F39_OPERATION_RELAY] = "RELAY",
    [F39_OPERATION_GPSDUP] = "GPSDUP",
    [F39_OPERATION_MLG] = "MLG",
    [F39_OPERATION_CAR] = "CAR",
    [F39_OPERATION_GPSBDS] = "GPSBDS",
    [F39_OPERATION_GMTSET] = "GMTSET",
    [F39_OPERATION_VIBSENS] = "VIBSENS",
    [F39_OPERATION_FKEY] = "FKEY",
    [F39_OPERATION_FOTA] = "FOTA",
    [F39_OPERATION_LOG] = "LOG",
};

bool f39_operation_name(f39_operation_t operation, const char **name)
{
    if(!name || operation<=F39_OPERATION_INVALID || operation>F39_OPERATION_LOG)return false;
    *name=s_roots[operation];return *name!=NULL;
}

static uint8_t f39_ascii_upper(uint8_t value)
{
    if ((value >= (uint8_t)'a') && (value <= (uint8_t)'z')) {
        return (uint8_t)(value - ((uint8_t)'a' - (uint8_t)'A'));
    }
    return value;
}

static uint8_t f39_root_equals(const uint8_t *data, uint16_t len, const char *name)
{
    uint16_t i;

    for (i = 0U; i < len; ++i) {
        if ((name[i] == '\0') || (f39_ascii_upper(data[i]) != (uint8_t)name[i])) {
            return 0U;
        }
    }
    return (uint8_t)(name[len] == '\0');
}

f39_operation_t f39_lookup_root(const uint8_t *data, uint16_t len)
{
    uint16_t i;

    if(!data || !len)return F39_OPERATION_INVALID;

    for (i = 1U; i < (uint16_t)(sizeof(s_roots) / sizeof(s_roots[0])); ++i) {
        if (f39_root_equals(data, len, s_roots[i]) != 0U) {
            return (f39_operation_t)i;
        }
    }
    return F39_OPERATION_INVALID;
}

static uint8_t f39_byte_allowed(uint8_t value)
{
    if ((value < (uint8_t)'!') || (value > (uint8_t)'~')) {
        return 0U;
    }
    return (uint8_t)((value != (uint8_t)'#') && (value != (uint8_t)'='));
}

static f39_result_t f39_parse_dualset(f39_request_t *out, uint16_t start)
{
    uint16_t cursor = start;
    uint16_t item_start = start;

    out->argc = 1U;
    out->args[0].offset = start;
    out->args[0].len = (uint16_t)(out->raw_len - start);
    while (cursor <= out->raw_len) {
        if ((cursor == out->raw_len) || (out->raw[cursor] == (uint8_t)'*')) {
            if (cursor == item_start) {
                return F39_RESULT_INVALID;
            }
            if (out->dualset_count >= F39_MAX_DUALSET_ITEMS) {
                return F39_RESULT_TOO_MANY_DUALSET_ITEMS;
            }
            out->dualset_items[out->dualset_count].offset = item_start;
            out->dualset_items[out->dualset_count].len = (uint16_t)(cursor - item_start);
            ++out->dualset_count;
            item_start = (uint16_t)(cursor + 1U);
        }
        ++cursor;
    }
    return F39_RESULT_OK;
}

static f39_result_t f39_parse_arguments(f39_request_t *out, uint16_t start)
{
    uint16_t cursor = start;
    uint16_t argument_start = start;

    while (cursor <= out->raw_len) {
        if ((cursor == out->raw_len) || (out->raw[cursor] == (uint8_t)',')) {
            /* APN credentials are optional; preserve empty username/password
             * positions. The APN itself and every other command stay strict. */
            if (cursor == argument_start &&
                !(out->operation == F39_OPERATION_APN &&
                  out->argc >= 1U && out->argc <= 2U)) {
                return F39_RESULT_INVALID;
            }
            if (out->argc >= F39_MAX_ARGUMENTS) {
                return F39_RESULT_TOO_MANY_ARGUMENTS;
            }
            out->args[out->argc].offset = argument_start;
            out->args[out->argc].len = (uint16_t)(cursor - argument_start);
            ++out->argc;
            argument_start = (uint16_t)(cursor + 1U);
        }
        ++cursor;
    }
    return F39_RESULT_OK;
}

f39_result_t f39_parse(const uint8_t *data, uint16_t len, f39_request_t *out)
{
    uint16_t root_len = 0U;
    uint16_t i;
    f39_result_t result;
    bool query_suffix = false;

    if (out == (f39_request_t *)0) {
        return F39_RESULT_INVALID;
    }
    (void)memset(out, 0, sizeof(*out));
    out->operation = F39_OPERATION_INVALID;
    if ((data == (const uint8_t *)0) || (len == 0U) || (len > F39_COMMAND_MAX_LENGTH)) {
        return F39_RESULT_INVALID;
    }
    for (i = 0U; i < len; ++i) {
        bool fkey_value_byte = root_len == 4U && i > root_len &&
                               f39_root_equals(data, root_len, "FKEY") != 0U &&
                               data[i] >= 0x20U && data[i] <= 0x7eU;
        if (f39_byte_allowed(data[i]) == 0U && !fkey_value_byte) {
            return F39_RESULT_INVALID;
        }
        if ((data[i] == (uint8_t)'*') && (root_len == 0U)) {
            return F39_RESULT_INVALID;
        }
        if ((data[i] == (uint8_t)',') && (root_len == 0U)) {
            root_len = i;
        }
        if (data[i] == (uint8_t)'?' && i + 1U == len && root_len == 0U) {
            root_len = i;
            query_suffix = true;
        }
    }
    if (root_len == 0U) {
        root_len = len;
    }
    out->operation = f39_lookup_root(data, root_len);
    if (out->operation == F39_OPERATION_INVALID) {
        return F39_RESULT_INVALID;
    }
    if (out->operation != F39_OPERATION_DUALSET &&
        out->operation != F39_OPERATION_FKEY) {
        for (i = (uint16_t)(root_len + 1U); i < len; ++i) {
            if (data[i] == (uint8_t)'*') {
                (void)memset(out, 0, sizeof(*out));
                out->operation = F39_OPERATION_INVALID;
                return F39_RESULT_INVALID;
            }
        }
    }
    (void)memcpy(out->raw, data, len);
    out->raw_len = len;
    if (root_len == len) {
        if (out->operation == F39_OPERATION_DUALSET) {
            (void)memset(out, 0, sizeof(*out));
            out->operation = F39_OPERATION_INVALID;
            return F39_RESULT_INVALID;
        }
        return F39_RESULT_OK;
    }
    if (query_suffix && (out->operation == F39_OPERATION_PARAM ||
                         out->operation == F39_OPERATION_FKEY ||
                         out->operation == F39_OPERATION_FOTA ||
                         out->operation == F39_OPERATION_LOG)) {
        return F39_RESULT_OK;
    }
    if ((out->operation == F39_OPERATION_PARAM) ||
        (out->operation == F39_OPERATION_RESET)) {
        (void)memset(out, 0, sizeof(*out));
        out->operation = F39_OPERATION_INVALID;
        return F39_RESULT_INVALID;
    }
    if (out->operation == F39_OPERATION_DUALSET) {
        result = f39_parse_dualset(out, (uint16_t)(root_len + 1U));
    } else {
        result = f39_parse_arguments(out, (uint16_t)(root_len + 1U));
    }
    if (result != F39_RESULT_OK) {
        (void)memset(out, 0, sizeof(*out));
        out->operation = F39_OPERATION_INVALID;
    }
    return result;
}
