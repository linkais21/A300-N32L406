#include "fota_check_parser.h"

#include <stddef.h>

typedef struct {
    const char *cursor;
    const char *end;
} fota_check_cursor_t;

enum {
    FOTA_CHECK_SEEN_UPDATE_AVAILABLE = 1U << 0,
    FOTA_CHECK_SEEN_VERSION_CODE = 1U << 1,
    FOTA_CHECK_SEEN_SIZE = 1U << 2,
    FOTA_CHECK_SEEN_DOWNLOAD_URL = 1U << 3,
    FOTA_CHECK_SEEN_SHA256 = 1U << 4,
    FOTA_CHECK_SEEN_SIGNATURE = 1U << 5,
    FOTA_CHECK_SEEN_SIGNING_KEY_ID = 1U << 6,
    FOTA_CHECK_SEEN_DOWNLOAD_TOKEN = 1U << 7,
    FOTA_CHECK_SEEN_ALL = FOTA_CHECK_SEEN_UPDATE_AVAILABLE |
                          FOTA_CHECK_SEEN_VERSION_CODE |
                          FOTA_CHECK_SEEN_SIZE |
                          FOTA_CHECK_SEEN_DOWNLOAD_URL |
                          FOTA_CHECK_SEEN_SHA256 |
                          FOTA_CHECK_SEEN_SIGNATURE |
                          FOTA_CHECK_SEEN_SIGNING_KEY_ID |
                          FOTA_CHECK_SEEN_DOWNLOAD_TOKEN
};

typedef enum {
    FOTA_CHECK_FIELD_UNKNOWN,
    FOTA_CHECK_FIELD_UPDATE_AVAILABLE,
    FOTA_CHECK_FIELD_VERSION_CODE,
    FOTA_CHECK_FIELD_SIZE,
    FOTA_CHECK_FIELD_DOWNLOAD_URL,
    FOTA_CHECK_FIELD_SHA256,
    FOTA_CHECK_FIELD_SIGNATURE,
    FOTA_CHECK_FIELD_SIGNING_KEY_ID,
    FOTA_CHECK_FIELD_DOWNLOAD_TOKEN
} fota_check_field_t;

static void fota_check_skip_whitespace(fota_check_cursor_t *cursor)
{
    while (cursor->cursor < cursor->end) {
        char value = *cursor->cursor;
        if (value != ' ' && value != '\t' && value != '\r' && value != '\n') {
            break;
        }
        cursor->cursor++;
    }
}

static bool fota_check_consume(fota_check_cursor_t *cursor, char expected)
{
    if (cursor->cursor >= cursor->end || *cursor->cursor != expected) {
        return false;
    }
    cursor->cursor++;
    return true;
}

static bool fota_check_parse_string(fota_check_cursor_t *cursor,
                                    const char **value, uint16_t *length,
                                    char *output, uint16_t output_size)
{
    const char *start;
    uint16_t count = 0U;

    if (!fota_check_consume(cursor, '"')) {
        return false;
    }
    start = cursor->cursor;
    while (cursor->cursor < cursor->end) {
        unsigned char character = (unsigned char)*cursor->cursor++;
        if (character == (unsigned char)'"') {
            if (value != NULL) {
                *value = start;
            }
            if (length != NULL) {
                *length = count;
            }
            if (output != NULL) {
                output[count] = '\0';
            }
            return true;
        }
        if (character == (unsigned char)'\\' || character < 0x20U) {
            return false;
        }
        if (output != NULL) {
            if (output_size == 0U || count >= (uint16_t)(output_size - 1U)) {
                return false;
            }
            output[count] = (char)character;
        }
        count++;
    }
    return false;
}

static bool fota_check_string_equals(const char *value, uint16_t length,
                                     const char *expected, uint16_t expected_length)
{
    uint16_t index;

    if (length != expected_length) {
        return false;
    }
    for (index = 0U; index < length; index++) {
        if (value[index] != expected[index]) {
            return false;
        }
    }
    return true;
}

static fota_check_field_t fota_check_field_for_key(const char *key, uint16_t length)
{
    if (fota_check_string_equals(key, length, "updateAvailable", 15U)) {
        return FOTA_CHECK_FIELD_UPDATE_AVAILABLE;
    }
    if (fota_check_string_equals(key, length, "versionCode", 11U)) {
        return FOTA_CHECK_FIELD_VERSION_CODE;
    }
    if (fota_check_string_equals(key, length, "size", 4U)) {
        return FOTA_CHECK_FIELD_SIZE;
    }
    if (fota_check_string_equals(key, length, "downloadUrl", 11U)) {
        return FOTA_CHECK_FIELD_DOWNLOAD_URL;
    }
    if (fota_check_string_equals(key, length, "sha256", 6U)) return FOTA_CHECK_FIELD_SHA256;
    if (fota_check_string_equals(key, length, "signature", 9U)) return FOTA_CHECK_FIELD_SIGNATURE;
    if (fota_check_string_equals(key, length, "signingKeyId", 12U)) return FOTA_CHECK_FIELD_SIGNING_KEY_ID;
    if (fota_check_string_equals(key, length, "downloadToken", 13U)) return FOTA_CHECK_FIELD_DOWNLOAD_TOKEN;
    return FOTA_CHECK_FIELD_UNKNOWN;
}

static bool fota_check_parse_literal(fota_check_cursor_t *cursor,
                                     const char *literal, uint16_t length)
{
    uint16_t index;

    if ((uint16_t)(cursor->end - cursor->cursor) < length) {
        return false;
    }
    for (index = 0U; index < length; index++) {
        if (cursor->cursor[index] != literal[index]) {
            return false;
        }
    }
    cursor->cursor += length;
    return true;
}

static bool fota_check_parse_bool(fota_check_cursor_t *cursor, bool *value)
{
    if (fota_check_parse_literal(cursor, "true", 4U)) {
        *value = true;
        return true;
    }
    if (fota_check_parse_literal(cursor, "false", 5U)) {
        *value = false;
        return true;
    }
    return false;
}

static bool fota_check_parse_u32(fota_check_cursor_t *cursor, uint32_t *value)
{
    uint32_t result = 0U;
    uint32_t digit;

    if (cursor->cursor >= cursor->end || *cursor->cursor < '0' ||
        *cursor->cursor > '9') {
        return false;
    }
    if (*cursor->cursor == '0') {
        cursor->cursor++;
        if (cursor->cursor < cursor->end && *cursor->cursor >= '0' &&
            *cursor->cursor <= '9') {
            return false;
        }
        *value = 0U;
        return true;
    }
    while (cursor->cursor < cursor->end && *cursor->cursor >= '0' &&
           *cursor->cursor <= '9') {
        digit = (uint32_t)(*cursor->cursor - '0');
        if (result > (UINT32_MAX - digit) / 10U) {
            return false;
        }
        result = result * 10U + digit;
        cursor->cursor++;
    }
    *value = result;
    return true;
}

static bool fota_check_skip_unknown_value(fota_check_cursor_t *cursor)
{
    if (cursor->cursor >= cursor->end) return false;
    if (*cursor->cursor == '"')
        return fota_check_parse_string(cursor, NULL, NULL, NULL, 0U);
    if (*cursor->cursor == 't') return fota_check_parse_literal(cursor, "true", 4U);
    if (*cursor->cursor == 'f') return fota_check_parse_literal(cursor, "false", 5U);
    if (*cursor->cursor == 'n') return fota_check_parse_literal(cursor, "null", 4U);
    if (*cursor->cursor >= '0' && *cursor->cursor <= '9') {
        uint32_t ignored;
        return fota_check_parse_u32(cursor, &ignored);
    }
    return false;
}

static uint8_t fota_check_field_bit(fota_check_field_t field)
{
    switch (field) {
    case FOTA_CHECK_FIELD_UPDATE_AVAILABLE:
        return FOTA_CHECK_SEEN_UPDATE_AVAILABLE;
    case FOTA_CHECK_FIELD_VERSION_CODE:
        return FOTA_CHECK_SEEN_VERSION_CODE;
    case FOTA_CHECK_FIELD_SIZE:
        return FOTA_CHECK_SEEN_SIZE;
    case FOTA_CHECK_FIELD_DOWNLOAD_URL:
        return FOTA_CHECK_SEEN_DOWNLOAD_URL;
    case FOTA_CHECK_FIELD_SHA256:
        return FOTA_CHECK_SEEN_SHA256;
    case FOTA_CHECK_FIELD_SIGNATURE:
        return FOTA_CHECK_SEEN_SIGNATURE;
    case FOTA_CHECK_FIELD_SIGNING_KEY_ID:
        return FOTA_CHECK_SEEN_SIGNING_KEY_ID;
    case FOTA_CHECK_FIELD_DOWNLOAD_TOKEN:
        return FOTA_CHECK_SEEN_DOWNLOAD_TOKEN;
    default:
        return 0U;
    }
}

bool fota_check_parse(const char *json, uint16_t length, fota_check_response_t *out)
{
    fota_check_cursor_t cursor;
    fota_check_response_t result = {0};
    uint8_t seen = 0U;

    if (json == NULL || out == NULL || length == 0U) {
        return false;
    }
    cursor.cursor = json;
    cursor.end = json + length;
    fota_check_skip_whitespace(&cursor);
    if (!fota_check_consume(&cursor, '{')) {
        return false;
    }
    fota_check_skip_whitespace(&cursor);
    if (fota_check_consume(&cursor, '}')) {
        return false;
    }

    for (;;) {
        const char *key;
        uint16_t key_length;
        fota_check_field_t field;
        uint8_t bit;

        if (!fota_check_parse_string(&cursor, &key, &key_length, NULL, 0U)) {
            return false;
        }
        field = fota_check_field_for_key(key, key_length);
        bit = fota_check_field_bit(field);
        if (bit != 0U && (seen & bit) != 0U) {
            return false;
        }
        if (bit != 0U) seen |= bit;
        fota_check_skip_whitespace(&cursor);
        if (!fota_check_consume(&cursor, ':')) {
            return false;
        }
        fota_check_skip_whitespace(&cursor);

        switch (field) {
        case FOTA_CHECK_FIELD_UPDATE_AVAILABLE:
            if (!fota_check_parse_bool(&cursor, &result.update_available)) {
                return false;
            }
            break;
        case FOTA_CHECK_FIELD_VERSION_CODE:
            if (!fota_check_parse_u32(&cursor, &result.version_code)) {
                return false;
            }
            break;
        case FOTA_CHECK_FIELD_SIZE:
            if (!fota_check_parse_u32(&cursor, &result.size)) {
                return false;
            }
            break;
        case FOTA_CHECK_FIELD_DOWNLOAD_URL:
            if (!fota_check_parse_string(&cursor, NULL, NULL, result.download_url,
                                         (uint16_t)sizeof(result.download_url))) {
                return false;
            }
            break;
        case FOTA_CHECK_FIELD_SHA256:
        case FOTA_CHECK_FIELD_SIGNATURE: {
            char text[129];
            uint16_t text_length, expected = field == FOTA_CHECK_FIELD_SHA256 ? 64U : 128U;
            uint8_t *target = field == FOTA_CHECK_FIELD_SHA256 ? result.package_sha256 : result.signature;
            if (!fota_check_parse_string(&cursor, NULL, &text_length, text, sizeof text) ||
                text_length != expected) return false;
            for (uint16_t i=0U;i<expected/2U;++i) {
                uint8_t hi,lo; char a=text[i*2U],b=text[i*2U+1U];
                if(a>='0'&&a<='9')hi=(uint8_t)(a-'0');else if(a>='a'&&a<='f')hi=(uint8_t)(a-'a'+10);else if(a>='A'&&a<='F')hi=(uint8_t)(a-'A'+10);else return false;
                if(b>='0'&&b<='9')lo=(uint8_t)(b-'0');else if(b>='a'&&b<='f')lo=(uint8_t)(b-'a'+10);else if(b>='A'&&b<='F')lo=(uint8_t)(b-'A'+10);else return false;
                target[i]=(uint8_t)((hi<<4)|lo);
            }
            break;
        }
        case FOTA_CHECK_FIELD_SIGNING_KEY_ID:
            if (!fota_check_parse_u32(&cursor, &result.signing_key_id) || result.signing_key_id == 0U) return false;
            break;
        case FOTA_CHECK_FIELD_DOWNLOAD_TOKEN:
            if (!fota_check_parse_string(&cursor, NULL, NULL, result.download_token,
                                         (uint16_t)sizeof(result.download_token)) ||
                result.download_token[0] == '\0') {
                return false;
            }
            break;
        default:
            if (!fota_check_skip_unknown_value(&cursor)) return false;
            break;
        }

        fota_check_skip_whitespace(&cursor);
        if (fota_check_consume(&cursor, '}')) {
            break;
        }
        if (!fota_check_consume(&cursor, ',')) {
            return false;
        }
        fota_check_skip_whitespace(&cursor);
    }

    fota_check_skip_whitespace(&cursor);
    if (cursor.cursor != cursor.end) {
        return false;
    }
    if ((seen & FOTA_CHECK_SEEN_UPDATE_AVAILABLE) == 0U) {
        return false;
    }
    if (result.update_available) {
        if (seen != FOTA_CHECK_SEEN_ALL) {
            return false;
        }
    } else if (seen != FOTA_CHECK_SEEN_UPDATE_AVAILABLE) {
        return false;
    }
    *out = result;
    return true;
}
