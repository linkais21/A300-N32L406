#include "f39_config_adapter.h"
#include "plate_encoding.h"

#include <limits.h>
#include <stddef.h>
#include <string.h>

#ifdef A300_FIRMWARE_IMAGE
#include "f39_production_bindings.h"
#endif

static bool argument(const f39_request_t *request, uint8_t index,
                     const uint8_t **data, uint16_t *length)
{
    uint32_t end;

    if (index >= request->argc) {
        return false;
    }
    end = (uint32_t)request->args[index].offset + request->args[index].len;
    if (end > request->raw_len) {
        return false;
    }
    *data = &request->raw[request->args[index].offset];
    *length = request->args[index].len;
    return true;
}

static bool parse_u32(const uint8_t *data, uint16_t length, uint32_t *value)
{
    uint32_t parsed = 0U;
    uint16_t i;

    if (length == 0U) {
        return false;
    }
    for (i = 0U; i < length; ++i) {
        uint32_t digit;
        if ((data[i] < (uint8_t)'0') || (data[i] > (uint8_t)'9')) {
            return false;
        }
        digit = (uint32_t)(data[i] - (uint8_t)'0');
        if (parsed > ((UINT32_MAX - digit) / 10U)) {
            return false;
        }
        parsed = parsed * 10U + digit;
    }
    *value = parsed;
    return true;
}

static bool parse_arg_u32(const f39_request_t *request, uint8_t index,
                          uint32_t *value)
{
    const uint8_t *data;
    uint16_t length;
    return argument(request, index, &data, &length) &&
           parse_u32(data, length, value);
}

static bool copy_arg(const f39_request_t *request, uint8_t index,
                     char *destination, size_t capacity, bool allow_empty)
{
    const uint8_t *data;
    uint16_t length;

    if (!argument(request, index, &data, &length) ||
        (!allow_empty && length == 0U) || (size_t)length >= capacity) {
        return false;
    }
    if (length != 0U) {
        (void)memcpy(destination, data, length);
    }
    destination[length] = '\0';
    return true;
}

static bool arg_equals(const f39_request_t *request, uint8_t index,
                       const char *text)
{
    const uint8_t *data;
    uint16_t length;
    size_t text_length = strlen(text);

    return argument(request, index, &data, &length) &&
           (size_t)length == text_length &&
           memcmp(data, text, text_length) == 0;
}

static bool valid_at_string_arg(const f39_request_t *request, uint8_t index,
                                bool allow_empty)
{
    const uint8_t *data;
    uint16_t length;
    uint16_t i;

    if (!argument(request, index, &data, &length) ||
        (!allow_empty && length == 0U)) {
        return false;
    }
    for (i = 0U; i < length; ++i) {
        if (data[i] < 0x20U || data[i] > 0x7eU || data[i] == (uint8_t)'"') {
            return false;
        }
    }
    return true;
}

static bool prepare_endpoint(const f39_request_t *request, char *host,
                             size_t host_capacity, uint16_t *port)
{
    uint32_t value;

    if (request->argc != 2U ||
        !copy_arg(request, 0U, host, host_capacity, false) ||
        !parse_arg_u32(request, 1U, &value) || value == 0U || value > 65535U) {
        return false;
    }
    *port = (uint16_t)value;
    return true;
}

/* Main and backup endpoints have identical commit effects; only FIP may
 * disable its endpoint with a single zero argument. */
static bool prepare_server(const f39_request_t *request,
                           device_config_t *candidate, uint32_t *effects)
{
    bool backup = request->operation == F39_OPERATION_FIP;
    char host[CFG_IP_LEN];
    uint16_t port;
    char *target = backup ? candidate->backup_ip : candidate->server_ip;
    uint16_t *target_port = backup ? &candidate->backup_port : &candidate->server_port;
    char *auth = backup ? candidate->backup_auth_code : candidate->auth_code;
    if (backup && arg_equals(request, 0U, "0")) {
        if (request->argc != 1U) return false;
        host[0] = '\0';
        port = 0U;
    } else if (!prepare_endpoint(request, host, sizeof(host), &port)) {
        return false;
    }
    if (strcmp(target, host) != 0 || *target_port != port) {
        (void)strcpy(target, host);
        *target_port = port;
        auth[0] = '\0';
        *effects |= backup ? F39_EFFECT_BACKUP_AUTH_RESET : F39_EFFECT_MAIN_AUTH_RESET;
    }
    *effects |= F39_EFFECT_NETWORK_RECONNECT;
    return true;
}

static bool prepare_freq(const f39_request_t *request,
                         device_config_t *candidate, uint32_t *effects)
{
    uint32_t moving;
    uint32_t stopped;

    if (request->argc != 2U || !parse_arg_u32(request, 0U, &moving) ||
        !parse_arg_u32(request, 1U, &stopped) || moving < 1U || moving > 300U ||
        stopped < 5U || stopped > 65535U) {
        return false;
    }
    candidate->report_moving_s = (uint16_t)moving;
    candidate->report_stopped_s = (uint16_t)stopped;
    candidate->sleep_report_mode = 0U;
    *effects |= F39_EFFECT_TIMER_REFRESH;
    return true;
}

static bool prepare_model(const f39_request_t *request,
                          device_config_t *candidate, uint32_t *effects)
{
    const uint8_t *data;
    uint16_t length;
    uint16_t i;

    if (request->argc != 1U || !argument(request, 0U, &data, &length) ||
        length < 1U || length > 20U) {
        return false;
    }
    for (i = 0U; i < length; ++i) {
        if (data[i] < 0x21U || data[i] > 0x7eU || data[i] == (uint8_t)',' ||
            data[i] == (uint8_t)'#') {
            return false;
        }
    }
    if (!copy_arg(request, 0U, candidate->terminal_model,
                  sizeof(candidate->terminal_model), false)) {
        return false;
    }
    *effects |= F39_EFFECT_JT808_REREGISTER |
                F39_EFFECT_REMAINING_REFRESH;
    return true;
}

static bool prepare_apn(const f39_request_t *request,
                        device_config_t *candidate, uint32_t *effects)
{
    if ((arg_equals(request, 0U, "AUTO") || arg_equals(request, 0U, "0"))) {
        if (request->argc != 1U &&
            !(request->argc == 3U && request->args[1].len == 0U &&
              request->args[2].len == 0U)) {
            return false;
        }
        candidate->autoapn_en = 1U;
        candidate->apn[0] = '\0';
        candidate->apn_user[0] = '\0';
        candidate->apn_pass[0] = '\0';
    } else {
        if (request->argc < 1U || request->argc > 3U ||
            !valid_at_string_arg(request, 0U, false) ||
            !copy_arg(request, 0U, candidate->apn, sizeof(candidate->apn), false)) {
            return false;
        }
        candidate->apn_user[0] = '\0';
        candidate->apn_pass[0] = '\0';
        if ((request->argc >= 2U) &&
            (!valid_at_string_arg(request, 1U, true) ||
            !copy_arg(request, 1U, candidate->apn_user,
                      sizeof(candidate->apn_user), true))) {
            return false;
        }
        if ((request->argc >= 3U) &&
            (!valid_at_string_arg(request, 2U, true) ||
            !copy_arg(request, 2U, candidate->apn_pass,
                      sizeof(candidate->apn_pass), true))) {
            return false;
        }
        candidate->autoapn_en = 0U;
    }
    *effects |= F39_EFFECT_MODEM_PDP_RESTART;
    return true;
}

static bool prepare_car(const f39_request_t *request,
                        device_config_t *candidate, uint32_t *effects)
{
    const uint8_t *data;
    uint16_t length;

    if (request->argc != 1U || !argument(request, 0U, &data, &length) ||
        length < 3U) {
        return false;
    }
    if (data[0] >= (uint8_t)'0' && data[0] <= (uint8_t)'9' &&
        data[1] >= (uint8_t)'0' && data[1] <= (uint8_t)'9') {
        uint8_t code = (uint8_t)((data[0] - (uint8_t)'0') * 10U +
                                 data[1] - (uint8_t)'0');
        const char *prefix = (const char *)plate_province_utf8(code);
        size_t prefix_length;
        size_t suffix_length = (size_t)length - 2U;
        if (prefix == NULL || code == 0U) {
            return false;
        }
        prefix_length = 3U;
        if (prefix_length + suffix_length >= sizeof(candidate->plate_no)) {
            return false;
        }
        (void)memcpy(candidate->plate_no, prefix, prefix_length);
        (void)memcpy(candidate->plate_no + prefix_length, data + 2U, suffix_length);
        candidate->plate_no[prefix_length + suffix_length] = '\0';
        *effects |= F39_EFFECT_JT808_REREGISTER;
        return true;
    }
    if (!copy_arg(request, 0U, candidate->plate_no,
                  sizeof(candidate->plate_no), false)) return false;
    *effects |= F39_EFFECT_JT808_REREGISTER;
    return true;
}

static bool prepare_gmt(const f39_request_t *request,
                        device_config_t *candidate)
{
    const uint8_t *data;
    uint16_t length;
    uint8_t hour;
    uint8_t minute;

    if (request->argc != 1U || !argument(request, 0U, &data, &length) ||
        length != 5U || (data[0] != (uint8_t)'E' && data[0] != (uint8_t)'W') ||
        data[1] < (uint8_t)'0' || data[1] > (uint8_t)'9' ||
        data[2] < (uint8_t)'0' || data[2] > (uint8_t)'9' ||
        data[3] < (uint8_t)'0' || data[3] > (uint8_t)'9' ||
        data[4] < (uint8_t)'0' || data[4] > (uint8_t)'9') {
        return false;
    }
    hour = (uint8_t)((data[1] - (uint8_t)'0') * 10U + data[2] - (uint8_t)'0');
    minute = (uint8_t)((data[3] - (uint8_t)'0') * 10U + data[4] - (uint8_t)'0');
    if (hour > 12U || minute > 59U) {
        return false;
    }
    candidate->gmt_sign = (int8_t)(data[0] == (uint8_t)'E' ? 1 : -1);
    candidate->gmt_hour = hour;
    candidate->gmt_min = minute;
    return true;
}

static bool prepare_pid(const f39_request_t *request,
                        device_config_t *candidate, uint32_t *effects)
{
    const uint8_t *data;
    uint16_t length;
    uint16_t i;
    if (request->argc != 1U || !argument(request, 0U, &data, &length) ||
        length != 11U) {
        return false;
    }
    for (i = 0U; i < length; ++i) {
        if (data[i] < (uint8_t)'0' || data[i] > (uint8_t)'9') {
            return false;
        }
    }
    if (!copy_arg(request, 0U, candidate->pid, sizeof(candidate->pid), false)) {
        return false;
    }
    *effects |= F39_EFFECT_JT808_REREGISTER |
                F39_EFFECT_REMAINING_REFRESH;
    return true;
}

static bool prepare_fkey(const f39_request_t *request,
                         device_config_t *candidate, uint32_t *effects)
{
    const uint8_t *data;
    uint16_t length;
    uint16_t i;

    if (request->argc != 1U || !argument(request, 0U, &data, &length) ||
        length < 16U || length >= CFG_DEVICE_API_KEY_LEN) {
        return false;
    }
    for (i = 0U; i < length; ++i) {
        if (data[i] < 0x20U || data[i] > 0x7eU) {
            return false;
        }
    }
    if (!copy_arg(request, 0U, candidate->device_api_key,
                  sizeof(candidate->device_api_key), false)) {
        return false;
    }
    *effects |= F39_EFFECT_FOTA_RECHECK;
    return true;
}

/* Apply one already parsed configuration operation to a candidate copy. */
static bool prepare_operation(const f39_request_t *request,
                              device_config_t *candidate, uint32_t *effects)
{
    uint32_t value;
    switch (request->operation) {
    case F39_OPERATION_HBT:
    case F39_OPERATION_SPEED:
    case F39_OPERATION_GPSDUP:
    case F39_OPERATION_MLG:
    case F39_OPERATION_GPSBDS:
    case F39_OPERATION_VIBSENS:
        /* Share strict scalar parsing without changing ranges or effects. */
        if (request->argc != 1U || !parse_arg_u32(request, 0U, &value)) return false;
        switch (request->operation) {
        case F39_OPERATION_HBT:
            if (value < 30U || value > 3600U) return false;
            candidate->heartbeat_s = (uint16_t)value;
            *effects |= F39_EFFECT_TIMER_REFRESH; break;
        case F39_OPERATION_SPEED:
            if (value < 20U || value > 200U) return false;
            candidate->speed_limit_kmh = (uint16_t)value; break;
        case F39_OPERATION_GPSDUP:
            if (value > 1U) return false;
            candidate->sleep_report_mode = (uint8_t)(value == 0U);
            *effects |= F39_EFFECT_TIMER_REFRESH; break;
        case F39_OPERATION_MLG:
            if (value > UINT32_MAX / 100U) return false;
            candidate->mileage_m = value * 100U; break;
        case F39_OPERATION_GPSBDS:
            if (value < 1U || value > 3U) return false;
            candidate->gpsbds_mode = (uint8_t)value;
            *effects |= F39_EFFECT_GNSS_REFRESH; break;
        default: /* VIBSENS: 1..50, smaller is more sensitive. */
            if (value < 1U || value > 50U) return false;
            candidate->vib_sens = (uint8_t)value; break;
        }
        return true;
    case F39_OPERATION_IP:
    case F39_OPERATION_FIP:
        return prepare_server(request, candidate, effects);
    case F39_OPERATION_FREQ:
        return prepare_freq(request, candidate, effects);
    case F39_OPERATION_MODEL:
        return prepare_model(request, candidate, effects);
    case F39_OPERATION_APN:
        return prepare_apn(request, candidate, effects);
    case F39_OPERATION_CAR:
        return prepare_car(request, candidate, effects);
    case F39_OPERATION_GMTSET:
        return prepare_gmt(request, candidate);
    case F39_OPERATION_FKEY:
        return prepare_fkey(request, candidate, effects);
    default:
        return false;
    }
}

static bool is_dualset_operation(f39_operation_t operation)
{
    switch (operation) {
    case F39_OPERATION_IP:
    case F39_OPERATION_FIP:
    case F39_OPERATION_FREQ:
    case F39_OPERATION_HBT:
    case F39_OPERATION_MODEL:
    case F39_OPERATION_SPEED:
    case F39_OPERATION_APN:
    case F39_OPERATION_GPSDUP:
    case F39_OPERATION_MLG:
    case F39_OPERATION_CAR:
    case F39_OPERATION_GPSBDS:
    case F39_OPERATION_GMTSET:
    case F39_OPERATION_VIBSENS:
        return true;
    default:
        return false;
    }
}

static bool prepare_dualset(const f39_request_t *request,
                            device_config_t *candidate, uint32_t *effects)
{
    /* Sized by the highest dualset-capable operation; VIBSENS now exceeds
     * GMTSET in the enum, so indexing it must stay in bounds. */
    bool seen[F39_OPERATION_VIBSENS + 1U] = { false };
    uint8_t i;

    if (request->dualset_count == 0U ||
        request->dualset_count > F39_MAX_DUALSET_ITEMS) {
        return false;
    }

    /* Validate into the private candidate in one pass. Nothing is persisted
     * or applied to hardware until every item passes and commit succeeds. */
    for (i = 0U; i < request->dualset_count; ++i) {
        f39_request_t item;
        const f39_argument_t *span = &request->dualset_items[i];
        if ((uint32_t)span->offset + span->len > request->raw_len ||
            f39_parse(&request->raw[span->offset], span->len, &item) !=
                F39_RESULT_OK ||
            !is_dualset_operation(item.operation) ||
            seen[item.operation]) {
            return false;
        }
        seen[item.operation] = true;
        if (!prepare_operation(&item, candidate, effects)) {
            return false;
        }
    }
    return true;
}

void f39_transaction_init(f39_transaction_t *transaction,
                          device_config_t *live,
                          f39_persist_config_fn persist,
                          void *persist_context)
{
    if (transaction != NULL) {
        (void)memset(transaction, 0, sizeof(*transaction));
        transaction->live = live;
        transaction->persist = persist;
        transaction->persist_context = persist_context;
    }
}

bool f39_prepare_config(const f39_request_t *request,
                        const device_config_t *current,
                        f39_transaction_t *transaction)
{
    bool valid = false;

    if (transaction != NULL) {
        transaction->prepared = false;
        transaction->effects = F39_EFFECT_NONE;
    }
    if (request == NULL || current == NULL || transaction == NULL ||
        transaction->live != current || transaction->persist == NULL) {
        return false;
    }
    transaction->candidate = *current;
    if (request->operation == F39_OPERATION_DUALSET) {
        valid = prepare_dualset(request, &transaction->candidate,
                                &transaction->effects);
    } else if (request->operation == F39_OPERATION_PID) {
        valid = prepare_pid(request, &transaction->candidate,
                            &transaction->effects);
    } else {
        valid = prepare_operation(request, &transaction->candidate,
                                  &transaction->effects);
    }
    if (!valid) {
        transaction->candidate = *current;
        transaction->effects = F39_EFFECT_NONE;
        return false;
    }
    /* A lost confirmation can redeliver APN indefinitely. Only a changed
     * profile needs PDP restart; preserve all other DUALSET effects. */
    if ((transaction->effects & F39_EFFECT_MODEM_PDP_RESTART) != 0U &&
        transaction->candidate.autoapn_en == current->autoapn_en &&
        strcmp(transaction->candidate.apn, current->apn) == 0 &&
        strcmp(transaction->candidate.apn_user, current->apn_user) == 0 &&
        strcmp(transaction->candidate.apn_pass, current->apn_pass) == 0) {
        transaction->effects &= ~F39_EFFECT_MODEM_PDP_RESTART;
    }
    transaction->prepared = true;
    return true;
}

f39_result_t f39_commit_config(f39_transaction_t *transaction)
{
    if (transaction == NULL || !transaction->prepared ||
        transaction->live == NULL || transaction->persist == NULL) {
        return F39_RESULT_INVALID;
    }
    transaction->prepared = false;
#ifdef A300_FIRMWARE_IMAGE
    if (transaction->persist != f39_production_persist ||
        !f39_production_persist(&transaction->candidate,
                                transaction->persist_context)) {
#else
    if (!transaction->persist(&transaction->candidate,
                              transaction->persist_context)) {
#endif
        transaction->effects = F39_EFFECT_NONE;
        return F39_RESULT_INVALID;
    }
    *transaction->live = transaction->candidate;
    return F39_RESULT_OK;
}
