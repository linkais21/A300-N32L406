#include "gps.h"
#include "config.h"
#include "hw_init.h"
#include "debug_uart.h"
#include "n32l40x.h"
#include <string.h>

#define NMEA_BUF_SIZE  128
#define NMEA_FIELD_MAX 24

static char      s_nmea_slots[2][NMEA_BUF_SIZE];
static volatile uint8_t s_nmea_pos;
static volatile uint8_t s_nmea_head;
static volatile uint8_t s_nmea_tail;
static volatile uint8_t s_nmea_count;
enum { NMEA_DROP_NONE, NMEA_DROP_QUEUE, NMEA_DROP_LENGTH };
static volatile uint8_t s_nmea_drop;
static gps_data_t s_gps = {0};
/* Compact STOP1 snapshot.  Keep the retained copy below 32 bytes; the full
 * gps_data_t contains doubles/floats and would exhaust the SRAM guard. */
typedef struct __attribute__((packed)) {
    int32_t lat_e7;
    int32_t lon_e7;
    uint16_t speed_x10;
    uint16_t heading_deg;
    int16_t altitude_m;
    uint16_t year;
    uint8_t month, day, hour, minute, second;
    uint8_t fix_quality, satellites;
} gps_retained_compact_t;
static gps_retained_compact_t s_last_trusted;
static bool s_last_trusted_valid;
static volatile gps_diag_t s_diag;

typedef enum {
    NMEA_PARSE_OK = 0,
    NMEA_PARSE_FORMAT,
    NMEA_PARSE_NO_FIX
} nmea_parse_result_t;


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
static bool parse_decimal(const char *s, double *out)
{
    uint32_t whole = 0U, fraction = 0U, divisor = 1U;
    uint8_t digits = 0U;
    bool negative = false, dot = false;
    if (s == NULL || out == NULL || *s == '\0') return false;
    if (*s == '-' || *s == '+') { negative = *s == '-'; ++s; }
    if (*s == '\0') return false;
    while (*s != '\0') {
        uint8_t digit;
        if (*s == '.') {
            if (dot) return false;
            dot = true; ++s; continue;
        }
        if (*s < '0' || *s > '9') return false;
        digit = (uint8_t)(*s - '0');
        if (!dot) {
            if (whole > (UINT32_MAX - digit) / 10U) return false;
            whole = whole * 10U + digit;
        } else {
            if (fraction > (UINT32_MAX - digit) / 10U ||
                divisor > UINT32_MAX / 10U) return false;
            fraction = fraction * 10U + digit;
            divisor *= 10U;
        }
        ++digits; ++s;
    }
    if (digits == 0U || (dot && divisor == 1U)) return false;
    *out = (double)whole + (double)fraction / (double)divisor;
    if (negative) *out = -*out;
    return true;
}

static bool parse_uint8(const char *s, uint8_t maximum, uint8_t *out)
{
    uint16_t value = 0U;
    uint8_t digits = 0U;
    if (s == NULL || out == NULL || *s == '\0') return false;
    while (*s != '\0') {
        if (*s < '0' || *s > '9' || digits >= 3U) return false;
        value = (uint16_t)(value * 10U + (uint8_t)(*s - '0'));
        ++digits; ++s;
    }
    if (value > maximum) return false;
    *out = (uint8_t)value;
    return true;
}

static bool parse_six_digits(const char *s, uint8_t *a, uint8_t *b, uint8_t *c)
{
    uint8_t i;
    if (s == NULL || a == NULL || b == NULL || c == NULL) return false;
    for (i = 0U; i < 6U; ++i) if (s[i] < '0' || s[i] > '9') return false;
    if (s[6] == '.') {
        i = 7U;
        if (s[i] == '\0') return false;
        while (s[i] != '\0') {
            if (s[i] < '0' || s[i] > '9') return false;
            ++i;
        }
    } else if (s[6] != '\0') return false;
    *a = (uint8_t)((s[0]-'0')*10 + s[1]-'0');
    *b = (uint8_t)((s[2]-'0')*10 + s[3]-'0');
    *c = (uint8_t)((s[4]-'0')*10 + s[5]-'0');
    return true;
}

static bool nmea_to_deg(const char *s, double *out)
{
    double raw, minutes;
    uint16_t degrees;
    if (!parse_decimal(s, &raw) || raw < 0.0) return false;
    degrees = (uint16_t)(raw / 100.0);
    minutes = raw - (double)degrees * 100.0;
    if (minutes >= 60.0) return false;
    *out = (double)degrees + minutes / 60.0;
    return true;
}

/* ── NMEA checksum verify ─────────────────────────────────────────────────── */
static bool nmea_checksum_ok(const char *sentence)
{
    uint8_t high, low;
    if (sentence[0] != '$') return false;
    const char *star = strchr(sentence, '*');
    if (!star) return false;
    uint8_t calc = 0;
    for (const char *p = sentence + 1; p < star; p++) calc ^= (uint8_t)*p;
    if (star[1] >= '0' && star[1] <= '9') high = (uint8_t)(star[1] - '0');
    else if (star[1] >= 'A' && star[1] <= 'F') high = (uint8_t)(star[1] - 'A' + 10);
    else return false;
    if (star[2] >= '0' && star[2] <= '9') low = (uint8_t)(star[2] - '0');
    else if (star[2] >= 'A' && star[2] <= 'F') low = (uint8_t)(star[2] - 'A' + 10);
    else return false;
    return (star[3] == '\r' || star[3] == '\n' || star[3] == '\0') &&
           calc == (uint8_t)((high << 4) | low);
}

/* ── Parse GGA ────────────────────────────────────────────────────────────── */
static nmea_parse_result_t parse_gga(char *s)
{
    /* $GPGGA,hhmmss.ss,llll.ll,a,yyyyy.yy,a,x,xx,x.x,x.x,M,...*hh */
    char *f[NMEA_FIELD_MAX];
    uint8_t n = nmea_split(s, f, NMEA_FIELD_MAX);
    if (n < 10) return NMEA_PARSE_FORMAT;

    uint8_t quality, satellites, hour, minute, second;
    double lat, lon, hdop, altitude, geoid = 0.0;
    if (!parse_uint8(f[6], 8U, &quality)) return NMEA_PARSE_FORMAT;
    if (quality == 0U) return NMEA_PARSE_NO_FIX;
    if (
        !parse_uint8(f[7], 99U, &satellites) ||
        !parse_decimal(f[8], &hdop) || !parse_decimal(f[9], &altitude) ||
        (n >= 12U && f[11][0] != '\0' && !parse_decimal(f[11], &geoid)) ||
        !nmea_to_deg(f[2], &lat) || !nmea_to_deg(f[4], &lon) ||
        !parse_six_digits(f[1], &hour, &minute, &second) ||
        hour > 23U || minute > 59U || second > 59U ||
        (f[3][0] != 'N' && f[3][0] != 'S') || f[3][1] != '\0' ||
        (f[5][0] != 'E' && f[5][0] != 'W') || f[5][1] != '\0') return NMEA_PARSE_FORMAT;
    s_gps.fix_quality = quality; s_gps.satellites = satellites;
    s_gps.hdop = (float)hdop; s_gps.altitude_m = (float)altitude;
    s_gps.geoid_sep_m = (float)geoid;
    s_gps.lat = f[3][0] == 'S' ? -lat : lat;
    s_gps.lon = f[5][0] == 'W' ? -lon : lon;
    s_gps.hour = hour; s_gps.minute = minute; s_gps.second = second;

    s_gps.valid          = true;
    s_gps.last_update_ms = TICK_MS();
    return NMEA_PARSE_OK;
}

/* ── Parse RMC ────────────────────────────────────────────────────────────── */
static nmea_parse_result_t parse_rmc(char *s)
{
    /* $GPRMC,hhmmss,A,llll.ll,a,yyyyy.yy,a,x.x,x.x,ddmmyy,...*hh */
    char *f[NMEA_FIELD_MAX];
    uint8_t n = nmea_split(s, f, NMEA_FIELD_MAX);
    if (n < 10) return NMEA_PARSE_FORMAT;
    if (f[2][0] == 'V' && f[2][1] == '\0') return NMEA_PARSE_NO_FIX;
    if (f[2][0] != 'A' || f[2][1] != '\0') return NMEA_PARSE_FORMAT;

    uint8_t hour, minute, second, day, month, year;
    double lat, lon, knots = 0.0, heading = 0.0;
    if (!parse_six_digits(f[1], &hour, &minute, &second) ||
        !nmea_to_deg(f[3], &lat) || !nmea_to_deg(f[5], &lon) ||
        (f[7][0] != '\0' && !parse_decimal(f[7], &knots)) ||
        (f[8][0] != '\0' && !parse_decimal(f[8], &heading)) ||
        !parse_six_digits(f[9], &day, &month, &year) ||
        hour > 23U || minute > 59U || second > 59U ||
        day == 0U || day > 31U || month == 0U || month > 12U ||
        knots < 0.0 || heading < 0.0 || heading >= 360.0 ||
        (f[4][0] != 'N' && f[4][0] != 'S') || f[4][1] != '\0' ||
        (f[6][0] != 'E' && f[6][0] != 'W') || f[6][1] != '\0') return NMEA_PARSE_FORMAT;
    s_gps.hour = hour; s_gps.minute = minute; s_gps.second = second;
    s_gps.lat = f[4][0] == 'S' ? -lat : lat;
    s_gps.lon = f[6][0] == 'W' ? -lon : lon;
    s_gps.speed_kmh = (float)(knots * 1.852);
    s_gps.heading = (float)heading;
    s_gps.day = day; s_gps.month = month; s_gps.year = (uint16_t)(2000U + year);

    s_gps.valid          = true;
    s_gps.last_update_ms = TICK_MS();
    s_gps.heading_update_ms = s_gps.last_update_ms;
    return NMEA_PARSE_OK;
}

/* ── Dispatch NMEA sentence ───────────────────────────────────────────────── */
static void __attribute__((noinline)) dispatch_nmea(char *sentence)
{
    nmea_parse_result_t result;
    ++s_diag.sentences;
    if (!nmea_checksum_ok(sentence)) {
        ++s_diag.checksum_fail;
        return;
    }

    /* skip talker ID (GP/GN/BD), compare sentence type */
    const char *type = sentence + 3;
    if (strncmp(type, "GGA,", 4) == 0) {
        ++s_diag.gga;
        result = parse_gga(sentence);
    } else if (strncmp(type, "RMC,", 4) == 0) {
        ++s_diag.rmc;
        result = parse_rmc(sentence);
    } else return;
    if (result == NMEA_PARSE_OK) ++s_diag.parsed;
    else if (result == NMEA_PARSE_NO_FIX) ++s_diag.no_fix;
    else ++s_diag.format_fail;
    /* GSV, GSA etc. can be added later */
}

/* ── Called from UART4 RX interrupt ──────────────────────────────────────── */
void gps_rx_isr(uint8_t byte)
{
    ++s_diag.rx_bytes;
    if (byte == '$') {
        s_nmea_pos = 0;
        s_nmea_drop = s_nmea_count >= 2U ? NMEA_DROP_QUEUE : NMEA_DROP_NONE;
    }
    if (!s_nmea_drop && s_nmea_pos < NMEA_BUF_SIZE - 1U) {
        s_nmea_slots[s_nmea_tail][s_nmea_pos++] = (char)byte;
    } else if (!s_nmea_drop) {
        s_nmea_drop = NMEA_DROP_LENGTH;
    }
    if (byte == '\n') {
        if (!s_nmea_drop && s_nmea_pos > 4U && s_nmea_count < 2U) {
            s_nmea_slots[s_nmea_tail][s_nmea_pos] = '\0';
            s_nmea_tail ^= 1U;
            ++s_nmea_count;
        } else if (s_nmea_drop) {
            ++s_diag.drop;
            if (s_nmea_drop == NMEA_DROP_QUEUE) ++s_diag.drop_queue;
            else ++s_diag.drop_length;
        }
        s_nmea_pos = 0;
        s_nmea_drop = false;
    }
}

/* UART4 IRQ handler */
void UART4_IRQHandler(void)
{
    /* Status followed by DAT clears OREF; sample before receiving the byte. */
    bool overrun = USART_GetFlagStatus(GPS_UART, USART_FLAG_OREF) != RESET;
    if (overrun) ++s_diag.overrun;
    if (USART_GetIntStatus(GPS_UART, USART_INT_RXDNE)) {
        uint8_t b = (uint8_t)USART_ReceiveData(GPS_UART);
        gps_rx_isr(b);
    } else if (overrun) {
        USART_ReceiveData(GPS_UART);
    }
}

/* ── Public API ───────────────────────────────────────────────────────────── */
void gps_init(void)
{
    memset(&s_gps, 0, sizeof(s_gps));
    memset(&s_last_trusted, 0, sizeof(s_last_trusted));
    s_last_trusted_valid = false;
    memset((void *)&s_diag, 0, sizeof(s_diag));
    s_nmea_pos = 0U;
    s_nmea_head = 0U;
    s_nmea_tail = 0U;
    s_nmea_count = 0U;
    s_nmea_drop = false;
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
    g.GPIO_Mode      = GPIO_Mode_Out_PP;
    g.GPIO_Slew_Rate = GPIO_Slew_Rate_High;
    g.GPIO_Current   = GPIO_DC_4mA;
    g.GPIO_Pull      = GPIO_No_Pull;
    GPIO_InitPeripheral(GPS_EN_PORT, &g);

    if (en) {
        GPIO_SetBits(GPS_EN_PORT, GPS_EN_PIN);
        delay_ms(100);
    } else {
        GPIO_ResetBits(GPS_EN_PORT, GPS_EN_PIN);
    }
}

void gps_process(void)
{
    if (s_nmea_count != 0U) {
        uint8_t slot = s_nmea_head;
        dispatch_nmea(s_nmea_slots[slot]);
        s_nmea_head ^= 1U;
        --s_nmea_count;
    }
    /* If no update in 5 s → invalid */
    if (s_gps.valid && (TICK_MS() - s_gps.last_update_ms) > 5000)
        s_gps.valid = false;
}

bool gps_is_valid(void)               { return s_gps.valid; }
const gps_data_t *gps_get_data(void)  { return &s_gps; }
/* True when the supplied civil time is strictly newer than the retained
 * snapshot's clock.  Compared field by field from the most significant, which
 * is exact for the UTC stamps GNSS supplies. */
static bool retained_clock_is_newer(uint16_t year, uint8_t month, uint8_t day,
                                    uint8_t hour, uint8_t minute, uint8_t second)
{
    uint32_t candidate_date = ((uint32_t)year << 9) |
                              ((uint32_t)month << 5) | (uint32_t)day;
    uint32_t retained_date = ((uint32_t)s_last_trusted.year << 9) |
                             ((uint32_t)s_last_trusted.month << 5) |
                             (uint32_t)s_last_trusted.day;
    uint32_t candidate_time, retained_time;

    if (candidate_date != retained_date) return candidate_date > retained_date;
    candidate_time = ((uint32_t)hour * 3600U) + ((uint32_t)minute * 60U) +
                     (uint32_t)second;
    retained_time = ((uint32_t)s_last_trusted.hour * 3600U) +
                    ((uint32_t)s_last_trusted.minute * 60U) +
                    (uint32_t)s_last_trusted.second;
    return candidate_time > retained_time;
}

bool gps_capture_last_trusted(void)
{
    uint32_t now = TICK_MS();

    if (!s_gps.valid || s_gps.fix_quality == 0U ||
        (uint32_t)(now - s_gps.last_update_ms) > 5000U ||
        s_gps.lat < -90.0 || s_gps.lat > 90.0 ||
        s_gps.lon < -180.0 || s_gps.lon > 180.0 ||
        (s_gps.lat == 0.0 && s_gps.lon == 0.0) ||
        s_gps.year < 2000U || s_gps.month < 1U || s_gps.month > 12U ||
        s_gps.day < 1U || s_gps.day > 31U || s_gps.hour > 23U ||
        s_gps.minute > 59U || s_gps.second > 59U) {
        return false;
    }
    /* Never let the retained clock run backwards.  While asleep this snapshot's
     * clock is pushed forward by gps_advance_last_trusted_seconds() on every
     * STOP1 wake, so a live fix whose own timestamp is older than the advanced
     * value would rewind reported time.  A field capture showed the retained
     * stamp going 06:41:17 -> 06:41:06 when ACC bounce drove repeated sleep
     * entries.  Position is still refreshed; only an older clock is refused. */
    if (s_last_trusted_valid &&
        !retained_clock_is_newer(s_gps.year, s_gps.month, s_gps.day,
                                 s_gps.hour, s_gps.minute, s_gps.second)) {
        return false;
    }
    s_last_trusted.lat_e7 = (int32_t)(s_gps.lat * 10000000.0);
    s_last_trusted.lon_e7 = (int32_t)(s_gps.lon * 10000000.0);
    s_last_trusted.speed_x10 = s_gps.speed_kmh <= 0.0f ? 0U :
        s_gps.speed_kmh >= 6553.5f ? 65535U : (uint16_t)(s_gps.speed_kmh * 10.0f);
    s_last_trusted.heading_deg = s_gps.heading >= 359.0f ? 359U :
        s_gps.heading < 0.0f ? 0U : (uint16_t)s_gps.heading;
    s_last_trusted.altitude_m = s_gps.altitude_m <= -32768.0f ? -32768 :
        s_gps.altitude_m >= 32767.0f ? 32767 : (int16_t)s_gps.altitude_m;
    s_last_trusted.year = s_gps.year;
    s_last_trusted.month = s_gps.month;
    s_last_trusted.day = s_gps.day;
    s_last_trusted.hour = s_gps.hour;
    s_last_trusted.minute = s_gps.minute;
    s_last_trusted.second = s_gps.second;
    s_last_trusted.fix_quality = s_gps.fix_quality;
    s_last_trusted.satellites = s_gps.satellites;
    s_last_trusted_valid = true;
    return true;
}

bool gps_get_last_trusted(gps_data_t *out)
{
    if (out == NULL || !s_last_trusted_valid) return false;
    memset(out, 0, sizeof(*out));
    out->lat = (double)s_last_trusted.lat_e7 / 10000000.0;
    out->lon = (double)s_last_trusted.lon_e7 / 10000000.0;
    out->speed_kmh = (float)s_last_trusted.speed_x10 / 10.0f;
    out->heading = (float)s_last_trusted.heading_deg;
    out->altitude_m = (float)s_last_trusted.altitude_m;
    out->geoid_sep_m = 0.0f;
    out->hdop = 0.0f;
    out->last_update_ms = TICK_MS();
    out->year = s_last_trusted.year;
    out->month = s_last_trusted.month;
    out->day = s_last_trusted.day;
    out->hour = s_last_trusted.hour;
    out->minute = s_last_trusted.minute;
    out->second = s_last_trusted.second;
    out->fix_quality = s_last_trusted.fix_quality;
    out->satellites = s_last_trusted.satellites;
    out->valid = true;
    return true;
}

void gps_advance_last_trusted_seconds(uint32_t elapsed_seconds)
{
    static const uint8_t days_in_month[13] =
        { 0U, 31U, 28U, 31U, 30U, 31U, 30U, 31U, 31U, 30U, 31U, 30U, 31U };
    uint32_t day_seconds;
    uint32_t total;
    uint8_t dim;
    bool leap;

    if (!s_last_trusted_valid || elapsed_seconds == 0U)
        return;
    day_seconds = (uint32_t)s_last_trusted.hour * 3600U +
                  (uint32_t)s_last_trusted.minute * 60U +
                  (uint32_t)s_last_trusted.second;
    total = day_seconds + elapsed_seconds;
    s_last_trusted.hour = (uint8_t)((total / 3600U) % 24U);
    s_last_trusted.minute = (uint8_t)((total % 3600U) / 60U);
    s_last_trusted.second = (uint8_t)(total % 60U);
    while (total >= 86400U) {
        total -= 86400U;
        leap = (s_last_trusted.year % 4U == 0U &&
                s_last_trusted.year % 100U != 0U) ||
               (s_last_trusted.year % 400U == 0U);
        dim = s_last_trusted.month == 2U && leap ? 29U :
              days_in_month[s_last_trusted.month];
        if (++s_last_trusted.day > dim) {
            s_last_trusted.day = 1U;
            if (++s_last_trusted.month > 12U) {
                s_last_trusted.month = 1U;
                ++s_last_trusted.year;
            }
        }
    }
}

void gps_apply_ntp_utc(uint16_t year, uint8_t month, uint8_t day,
                       uint8_t hour, uint8_t minute, uint8_t second)
{
    if (!s_last_trusted_valid ||
        year < 2000U || month < 1U || month > 12U ||
        day < 1U || day > 31U || hour > 23U || minute > 59U || second > 59U)
        return;
    s_last_trusted.year = year;
    s_last_trusted.month = month;
    s_last_trusted.day = day;
    s_last_trusted.hour = hour;
    s_last_trusted.minute = minute;
    s_last_trusted.second = second;
}

void gps_resume_after_wake(void)
{
    /* STOP1 leaves the UART configuration intact.  Re-request GGA/RMC
     * output only; gps_init() would erase the retained STOP1 snapshot. */
    gps_send_cmd("$PCAS03,1,0,0,0,1,0,0,0,0,0,,,0,0*02\r\n");
}

const volatile gps_diag_t *gps_get_diag(void) { return &s_diag; }

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
