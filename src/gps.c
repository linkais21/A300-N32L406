#include "gps.h"
#include "config.h"
#include "hw_init.h"
#include "debug_uart.h"
#include "n32l40x.h"
#include <string.h>
#include <stdlib.h>
#include <math.h>

#define NMEA_BUF_SIZE  128
#define NMEA_FIELD_MAX 24

static char      s_nmea_buf[NMEA_BUF_SIZE];
static uint8_t   s_nmea_pos = 0;
static gps_data_t s_gps = {0};


/* ── Helper: split NMEA sentence into fields ──────────────────────────────── */
static uint8_t nmea_split(char *sentence, char **fields, uint8_t max_fields)
{
    uint8_t n = 0;
    fields[n++] = sentence;
    for (char *p = sentence; *p && n < max_fields; p++) {
        if (*p == ',' || *p == '*') {
            *p = '\0';
            fields[n++] = p + 1;
        }
    }
    return n;
}

/* ── NMEA degree/minute → decimal degrees ────────────────────────────────── */
static double nmea_to_deg(const char *s)
{
    if (!s || !*s) return 0.0;
    double raw = atof(s);
    int deg = (int)(raw / 100);
    double min = raw - deg * 100.0;
    return deg + min / 60.0;
}

/* ── NMEA checksum verify ─────────────────────────────────────────────────── */
static bool nmea_checksum_ok(const char *sentence)
{
    if (sentence[0] != '$') return false;
    const char *star = strchr(sentence, '*');
    if (!star) return false;
    uint8_t calc = 0;
    for (const char *p = sentence + 1; p < star; p++) calc ^= (uint8_t)*p;
    uint8_t got = (uint8_t)strtol(star + 1, NULL, 16);
    return calc == got;
}

/* ── Parse GGA ────────────────────────────────────────────────────────────── */
static void parse_gga(char *s)
{
    /* $GPGGA,hhmmss.ss,llll.ll,a,yyyyy.yy,a,x,xx,x.x,x.x,M,...*hh */
    char *f[NMEA_FIELD_MAX];
    uint8_t n = nmea_split(s, f, NMEA_FIELD_MAX);
    if (n < 10) return;

    s_gps.fix_quality = (uint8_t)atoi(f[6]);
    s_gps.satellites  = (uint8_t)atoi(f[7]);
    s_gps.hdop        = (float)atof(f[8]);
    s_gps.altitude_m  = (float)atof(f[9]);   /* antenna height above MSL */
    if (n >= 12) s_gps.geoid_sep_m = (float)atof(f[11]); /* geoid separation */

    if (s_gps.fix_quality == 0) return;

    s_gps.lat = nmea_to_deg(f[2]);
    if (f[3][0] == 'S') s_gps.lat = -s_gps.lat;
    s_gps.lon = nmea_to_deg(f[4]);
    if (f[5][0] == 'W') s_gps.lon = -s_gps.lon;

    /* parse UTC time hhmmss.ss */
    const char *t = f[1];
    if (strlen(t) >= 6) {
        s_gps.hour   = (t[0]-'0')*10 + (t[1]-'0');
        s_gps.minute = (t[2]-'0')*10 + (t[3]-'0');
        s_gps.second = (t[4]-'0')*10 + (t[5]-'0');
    }

    s_gps.valid          = true;
    s_gps.last_update_ms = TICK_MS();
}

/* ── Parse RMC ────────────────────────────────────────────────────────────── */
static void parse_rmc(char *s)
{
    /* $GPRMC,hhmmss,A,llll.ll,a,yyyyy.yy,a,x.x,x.x,ddmmyy,...*hh */
    char *f[NMEA_FIELD_MAX];
    uint8_t n = nmea_split(s, f, NMEA_FIELD_MAX);
    if (n < 10) return;
    if (f[2][0] != 'A') return;   /* not valid */

    const char *t = f[1];
    if (strlen(t) >= 6) {
        s_gps.hour   = (t[0]-'0')*10 + (t[1]-'0');
        s_gps.minute = (t[2]-'0')*10 + (t[3]-'0');
        s_gps.second = (t[4]-'0')*10 + (t[5]-'0');
    }

    s_gps.lat = nmea_to_deg(f[3]);
    if (f[4][0] == 'S') s_gps.lat = -s_gps.lat;
    s_gps.lon = nmea_to_deg(f[5]);
    if (f[6][0] == 'W') s_gps.lon = -s_gps.lon;
    s_gps.speed_kmh = (float)atof(f[7]) * 1.852f;
    s_gps.heading   = (float)atof(f[8]);

    const char *d = f[9];
    if (strlen(d) >= 6) {
        s_gps.day   = (d[0]-'0')*10 + (d[1]-'0');
        s_gps.month = (d[2]-'0')*10 + (d[3]-'0');
        s_gps.year  = 2000 + (d[4]-'0')*10 + (d[5]-'0');
    }

    s_gps.valid          = true;
    s_gps.last_update_ms = TICK_MS();
}

/* ── Dispatch NMEA sentence ───────────────────────────────────────────────── */
static void dispatch_nmea(char *sentence)
{
    if (!nmea_checksum_ok(sentence)) return;

    /* skip talker ID (GP/GN/BD), compare sentence type */
    const char *type = sentence + 3;
    if (strncmp(type, "GGA,", 4) == 0) parse_gga(sentence);
    else if (strncmp(type, "RMC,", 4) == 0) parse_rmc(sentence);
    /* GSV, GSA etc. can be added later */
}

/* ── Called from UART4 RX interrupt ──────────────────────────────────────── */
void gps_rx_isr(uint8_t byte)
{
    if (byte == '$') {
        s_nmea_pos = 0;
    }
    if (s_nmea_pos < NMEA_BUF_SIZE - 1) {
        s_nmea_buf[s_nmea_pos++] = (char)byte;
    }
    if (byte == '\n' && s_nmea_pos > 4) {
        s_nmea_buf[s_nmea_pos] = '\0';
        dispatch_nmea(s_nmea_buf);
        s_nmea_pos = 0;
    }
}

/* UART4 IRQ handler */
void UART4_IRQHandler(void)
{
    if (USART_GetIntStatus(GPS_UART, USART_INT_RXDNE)) {
        uint8_t b = (uint8_t)USART_ReceiveData(GPS_UART);
        gps_rx_isr(b);
    }
    if (USART_GetFlagStatus(GPS_UART, USART_FLAG_OREF)) {
        USART_ReceiveData(GPS_UART);
    }
}

/* ── Public API ───────────────────────────────────────────────────────────── */
void gps_init(void)
{
    memset(&s_gps, 0, sizeof(s_gps));
    /* TAU804M: enable NMEA GGA+RMC at 1 Hz via $PCAS03 */
    /* $PCAS03,1,0,0,0,1,0,0,0,0,0,,,0,0*xx format */
    delay_ms(500);
    gps_send_cmd("$PCAS03,1,0,0,0,1,0,0,0,0,0,,,0,0*02\r\n");
}

void gps_enable(bool en)
{
    GPIO_InitType g;
    GPIO_InitStruct(&g);
    g.Pin            = GPS_EN_PIN;
    g.GPIO_Slew_Rate = GPIO_Slew_Rate_High;
    g.GPIO_Current   = GPIO_DC_4mA;

    if (en) {
        /* Drive HIGH as GPIO_PP to charge LDO EN input */
        g.GPIO_Mode = GPIO_Mode_Out_PP;
        g.GPIO_Pull = GPIO_No_Pull;
        GPIO_InitPeripheral(GPS_EN_PORT, &g);
        GPIO_SetBits(GPS_EN_PORT, GPS_EN_PIN);
        delay_ms(10);
        /* Switch back to I2C1_SCL (AF_OD + R17 4.7K pull-up holds SCL HIGH
         * during idle → LDO EN stays HIGH → GPS_VCC stays on) */
        g.GPIO_Mode      = GPIO_Mode_AF_OD;
        g.GPIO_Pull      = GPIO_Pull_Up;
        g.GPIO_Alternate = GPIO_AF4_I2C1;
        GPIO_InitPeripheral(GPS_EN_PORT, &g);
        delay_ms(100);
    } else {
        /* Drive LOW to cut LDO power */
        g.GPIO_Mode = GPIO_Mode_Out_PP;
        g.GPIO_Pull = GPIO_No_Pull;
        GPIO_InitPeripheral(GPS_EN_PORT, &g);
        GPIO_ResetBits(GPS_EN_PORT, GPS_EN_PIN);
    }
}

void gps_process(void)
{    /* If no update in 5 s → invalid */
    if (s_gps.valid && (TICK_MS() - s_gps.last_update_ms) > 5000)
        s_gps.valid = false;
}

bool gps_is_valid(void)               { return s_gps.valid; }
const gps_data_t *gps_get_data(void)  { return &s_gps; }

static bool gps_tx_write(const uint8_t *data, uint32_t len)
{
    uint32_t timeout_ms = 100U + ((len + 7U) / 8U);
    uint32_t start_ms = TICK_MS();
    uint32_t guard = timeout_ms * 1024U + 1U;

    for (uint32_t i = 0U; i < len; ++i) {
        while (USART_GetFlagStatus(GPS_UART, USART_FLAG_TXDE) == RESET) {
            if ((uint32_t)(TICK_MS() - start_ms) >= timeout_ms || guard == 0U)
                return false;
            --guard;
            IWDG_ReloadKey();
        }
        USART_SendData(GPS_UART, data[i]);
    }

    while (USART_GetFlagStatus(GPS_UART, USART_FLAG_TXC) == RESET) {
        if ((uint32_t)(TICK_MS() - start_ms) >= timeout_ms || guard == 0U)
            return false;
        --guard;
        IWDG_ReloadKey();
    }
    return true;
}

void gps_send_cmd(const char *cmd)
{
    if (!cmd || !*cmd) return;
    (void)gps_tx_write((const uint8_t *)cmd, (uint32_t)strlen(cmd));
}

int gps_send_raw(const uint8_t *data, uint32_t len)
{
    if (!data || len == 0U || len > 65535UL) return -1;
    return gps_tx_write(data, len) ? 0 : -1;
}
