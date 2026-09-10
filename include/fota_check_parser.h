#ifndef FOTA_CHECK_PARSER_H
#define FOTA_CHECK_PARSER_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    bool update_available;
    uint32_t version_code;
    uint32_t size;
    char download_url[128];
    uint8_t package_sha256[32];
    uint8_t signature[64];
    uint32_t signing_key_id;
    char download_token[32];
} fota_check_response_t;

bool fota_check_parse(const char *json, uint16_t length,
                      fota_check_response_t *out);

#endif
