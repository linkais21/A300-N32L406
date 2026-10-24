#ifndef A300_FORMAT_H
#define A300_FORMAT_H

#include <stdarg.h>
#include <stddef.h>

int a300_snprintf(char *buffer, size_t capacity, const char *format, ...);
int a300_vsnprintf(char *buffer, size_t capacity, const char *format, va_list arguments);

#ifdef A300_COMPACT_FORMAT
#define snprintf a300_snprintf
#define vsnprintf a300_vsnprintf
#endif

#endif
