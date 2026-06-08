#ifndef GPS_H
#define GPS_H

#include <stdint.h>
#include <stdbool.h>

typedef struct {
    double   lat;           /* degrees, positive=N */
    double   lon;           /* degrees, positive=E */
    float    speed_kmh;
    float    heading;       /* degrees true */
    float    altitude_m;    /* GGA f[9]: antenna height above MSL, metres */
    float    geoid_sep_m;   /* GGA f[11]: geoid separation, metres */
    uint8_t  fix_quality;   /* 0=invalid 1=GPS 2=DGPS 4=RTK */
    uint8_t  satellites;
    float    hdop;
    uint16_t year;
    uint8_t  month;
    uint8_t  day;
    uint8_t  hour;
    uint8_t  minute;
    uint8_t  second;
    bool     valid;
    uint32_t last_update_ms;
} gps_data_t;

void gps_init(void);
void gps_enable(bool en);           /* power gate via GPS_EN */
void gps_process(void);             /* call from main loop  */
bool gps_is_valid(void);
const gps_data_t *gps_get_data(void);

/* Called from UART4_IRQHandler */
void gps_rx_isr(uint8_t byte);

/* Send CASIC command to GPS module */
void gps_send_cmd(const char *cmd);

#endif
