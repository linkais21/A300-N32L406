#ifndef LOG_PLATFORM_H
#define LOG_PLATFORM_H
#include <stdbool.h>
#include <stdint.h>
#define LOG_PLATFORM_HOST "39.108.211.33"
#define LOG_PLATFORM_PORT 10009U
void log_platform_init(void);
void log_platform_process(void);
void log_platform_on_first_online(void);
void log_platform_on_blind_zone_uploaded(void);
#endif
