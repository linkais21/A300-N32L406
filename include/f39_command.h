#ifndef F39_COMMAND_H
#define F39_COMMAND_H

#include <stdint.h>

#define F39_COMMAND_MAX_LENGTH       191U
#define F39_MAX_ARGUMENTS             8U
#define F39_MAX_DUALSET_ITEMS         8U

typedef enum {
    F39_RESULT_OK = 0,
    F39_RESULT_INVALID,
    F39_RESULT_TOO_MANY_ARGUMENTS,
    F39_RESULT_TOO_MANY_DUALSET_ITEMS
} f39_result_t;

typedef enum {
    F39_OPERATION_INVALID = 0,
    F39_OPERATION_PARAM,
    F39_OPERATION_DUALSET,
    F39_OPERATION_RESET,
    F39_OPERATION_PID,
    F39_OPERATION_IP,
    F39_OPERATION_FIP,
    F39_OPERATION_FREQ,
    F39_OPERATION_HBT,
    F39_OPERATION_MODEL,
    F39_OPERATION_SPEED,
    F39_OPERATION_APN,
    F39_OPERATION_RELAY,
    F39_OPERATION_GPSDUP,
    F39_OPERATION_MLG,
    F39_OPERATION_CAR,
    F39_OPERATION_GPSBDS,
    F39_OPERATION_GMTSET,
    F39_OPERATION_FOTA,
    F39_OPERATION_LOG
} f39_operation_t;

typedef struct {
    uint16_t offset;
    uint16_t len;
} f39_argument_t;

typedef struct {
    f39_operation_t operation;
    uint8_t argc;
    uint8_t dualset_count;
    uint16_t raw_len;
    uint8_t raw[F39_COMMAND_MAX_LENGTH];
    f39_argument_t args[F39_MAX_ARGUMENTS];
    f39_argument_t dualset_items[F39_MAX_DUALSET_ITEMS];
} f39_request_t;

/*
 * Parses canonical SMS command text after ingress removed its trailing '#'.
 * Argument offsets refer to out->raw and therefore remain valid without
 * retaining the caller's ingress buffer.
 */
f39_result_t f39_parse(const uint8_t *data, uint16_t len, f39_request_t *out);

#endif
