#include "a300_format.h"
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>

typedef struct {
    char *buffer;
    size_t capacity;
    int length;
} format_output_t;

static bool emit(format_output_t *output, char value)
{
    if (output->length == INT_MAX) return false;
    if (output->capacity != 0U && (size_t)output->length < output->capacity - 1U)
        output->buffer[output->length] = value;
    output->length++;
    return true;
}

static bool emit_padding(format_output_t *output, int count, char value)
{
    while (count-- > 0) {
        if (!emit(output, value)) return false;
    }
    return true;
}

static bool emit_number(format_output_t *output, unsigned long magnitude,
                        bool negative, unsigned base, bool upper,
                        int width, bool zero_pad)
{
    char digits[3U * sizeof(unsigned long)];
    int count = 0;
    do {
        unsigned digit = (unsigned)(magnitude % base);
        digits[count++] = (char)(digit < 10U ? '0' + digit :
                                 (upper ? 'A' : 'a') + digit - 10U);
        magnitude /= base;
    } while (magnitude != 0U);
    int padding = width - count - (negative ? 1 : 0);
    if (!zero_pad && !emit_padding(output, padding, ' ')) return false;
    if (negative && !emit(output, '-')) return false;
    if (zero_pad && !emit_padding(output, padding, '0')) return false;
    while (count-- > 0) {
        if (!emit(output, digits[count])) return false;
    }
    return true;
}

static int format_error(format_output_t *output)
{
    if (output->capacity != 0U) output->buffer[0] = '\0';
    return -1;
}

int a300_vsnprintf(char *buffer, size_t capacity, const char *format, va_list arguments)
{
    format_output_t output = {buffer, capacity, 0};
    if (format == NULL || (capacity != 0U && buffer == NULL)) return -1;
    if (capacity != 0U) buffer[0] = '\0';
    while (*format != '\0') {
        if (*format != '%') {
            if (!emit(&output, *format++)) return format_error(&output);
            continue;
        }
        format++;
        bool zero_pad = *format == '0';
        if (zero_pad) format++;
        int width = 0;
        while (*format >= '0' && *format <= '9') {
            int digit = *format++ - '0';
            if (width > (1024 - digit) / 10) return format_error(&output);
            width = width * 10 + digit;
        }
        int precision = -1;
        if (*format == '.') {
            format++;
            precision = 0;
            if (*format == '*') {
                precision = va_arg(arguments, int);
                format++;
            } else {
                while (*format >= '0' && *format <= '9') {
                    int digit = *format++ - '0';
                    if (precision > (1024 - digit) / 10) return format_error(&output);
                    precision = precision * 10 + digit;
                }
            }
        }
        bool long_value = *format == 'l';
        if (long_value) format++;
        char specifier = *format++;
        if (specifier == 's' && !long_value) {
            const char *value = va_arg(arguments, const char *);
            if (value == NULL) value = "(null)";
            int length = 0;
            while (value[length] != '\0' && (precision < 0 || length < precision)) {
                if (length == INT_MAX) return format_error(&output);
                length++;
            }
            if (!emit_padding(&output, width - length, ' ')) return format_error(&output);
            for (int index = 0; index < length; index++) {
                if (!emit(&output, value[index])) return format_error(&output);
            }
        } else if (specifier == 'c' && !long_value && precision < 0) {
            if (!emit_padding(&output, width - 1, ' ') ||
                !emit(&output, (char)va_arg(arguments, int))) return format_error(&output);
        } else if (specifier == '%' && !long_value && precision < 0) {
            if (!emit(&output, '%')) return format_error(&output);
        } else if ((specifier == 'd' || specifier == 'i' || specifier == 'u' ||
                    specifier == 'x' || specifier == 'X') && precision < 0) {
            unsigned long magnitude;
            bool negative = false;
            if (specifier == 'd' || specifier == 'i') {
                long value = long_value ? va_arg(arguments, long) : va_arg(arguments, int);
                negative = value < 0;
                magnitude = negative ? 0UL - (unsigned long)value : (unsigned long)value;
            } else {
                magnitude = long_value ? va_arg(arguments, unsigned long) :
                                         va_arg(arguments, unsigned int);
            }
            if (!emit_number(&output, magnitude, negative,
                             specifier == 'x' || specifier == 'X' ? 16U : 10U,
                             specifier == 'X', width, zero_pad)) return format_error(&output);
        } else {
            return format_error(&output);
        }
    }
    if (capacity != 0U) {
        size_t terminator = (size_t)output.length < capacity ?
                            (size_t)output.length : capacity - 1U;
        buffer[terminator] = '\0';
    }
    return output.length;
}

int a300_snprintf(char *buffer, size_t capacity, const char *format, ...)
{
    va_list arguments;
    va_start(arguments, format);
    int length = a300_vsnprintf(buffer, capacity, format, arguments);
    va_end(arguments);
    return length;
}
