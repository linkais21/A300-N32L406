#ifndef JT808_TERMINAL_INFO_H
#define JT808_TERMINAL_INFO_H

#include <stdbool.h>
#include <stdint.h>

#define JT808_TERMINAL_INFO_BODY_LENGTH 83U

typedef enum {
    JT808_TERMINAL_INFO_OK = 0,
    JT808_TERMINAL_INFO_INVALID_ARGUMENT,
    JT808_TERMINAL_INFO_INVALID_IDENTITY,
    JT808_TERMINAL_INFO_INVALID_ICCID,
    JT808_TERMINAL_INFO_NO_SPACE,
} jt808_terminal_info_result_t;

jt808_terminal_info_result_t jt808_terminal_info_encode(
    uint8_t *body, uint16_t capacity, uint16_t *length);

#endif
