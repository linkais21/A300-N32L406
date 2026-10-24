#ifndef CIVIL_DATE_H
#define CIVIL_DATE_H
#include <stdint.h>
/* Shared by NMEA validation, retained UTC and JT808 timezone rollover. */
static __attribute__((noinline)) uint8_t civil_month_days(uint16_t year, uint8_t month)
{
    static const uint8_t days[] = {0,31,28,31,30,31,30,31,31,30,31,30,31};
    if (month > 12U) return 0U;
    return month == 2U && year % 4U == 0U &&
           (year % 100U != 0U || year % 400U == 0U) ? 29U : days[month];
}
#endif
