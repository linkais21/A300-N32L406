#include "gps.h"
#include "config.h"
#include "hw_init.h"
#include "debug_uart.h"
#include "n32l40x.h"
#include <string.h>
#include <math.h>

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
static bool s_enabled = true;
bool gps_is_enabled(void) { return s_enabled; }
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
static uint32_t s_last_trusted_tick_ms;
static volatile gps_diag_t s_diag;
static uint32_t s_gga_ms;
static uint32_t s_trace_started;
static uint8_t s_trace_remaining;

void gps_trace_start(void)
{
    s_trace_started = TICK_MS();
    s_trace_remaining = 32U;
}
typedef struct {
    uint32_t updated;
    uint16_t sum;
    uint8_t count, maximum, next, pages, satellites, signal;
} gsv_cycle_t;
/* GP, BD/GB, GN: the product's GPS/BDS modes. One signal band avoids
 * counting the same satellite twice on receivers with NMEA 4.1 GSV. */
static gsv_cycle_t s_gsv[3];

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
    if (quality == 0U) {
        s_gps.fix_quality = 0U;
        s_gps.valid = false;
        return NMEA_PARSE_NO_FIX;
    }
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
    s_gga_ms = TICK_MS();
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
    if (f[2][0] == 'V' && f[2][1] == '\0') {
        s_gps.valid = false;
        return NMEA_PARSE_NO_FIX;
    }
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

static void parse_gsv(char *sentence)
{
    unsigned slot;
    if (sentence[1] == 'G' && sentence[2] == 'P') slot = 0U;
    else if ((sentence[1] == 'B' && sentence[2] == 'D') ||
             (sentence[1] == 'G' && sentence[2] == 'B')) slot = 1U;
    else if (sentence[1] == 'G' && sentence[2] == 'N') slot = 2U;
    else return;
    char *f[NMEA_FIELD_MAX];
    uint8_t n = nmea_split(sentence, f, NMEA_FIELD_MAX);
    uint8_t pages, page, sats, signal = 0U;
    if (n < 5U || !parse_uint8(f[1], 16U, &pages) || pages == 0U ||
        !parse_uint8(f[2], pages, &page) || page == 0U ||
        !parse_uint8(f[3], 64U, &sats)) return;
    bool has_signal = n >= 6U && (n - 6U) % 4U == 0U;
    unsigned groups;
    if (has_signal) {
        groups = (n - 6U) / 4U;
        if (groups > 4U || !parse_uint8(f[4U + groups * 4U], 15U, &signal)) return;
    } else {
        if (pages != (sats ? (sats + 3U) / 4U : 1U)) return;
        groups = sats == 0U ? 0U : (page < pages ? 4U : sats - (pages - 1U) * 4U);
        if (n != 5U + groups * 4U) return;
    }
    gsv_cycle_t *c = &s_gsv[slot];
    uint32_t now = TICK_MS();
    bool expired = (uint32_t)(now - c->updated) > 5000U;
    /* Huada may number pages across bands (including short non-final pages).
     * Consume the whole sequence, but count only its first band. Independent
     * interleaved band cycles must not replace the selected band's cycle. */
    if (c->next != 0U && !expired && c->signal != signal &&
        !(page != 1U && page == c->next && pages == c->pages && sats == c->satellites)) return;
    if (page == 1U) {
        memset(c, 0, sizeof(*c));
        c->pages = pages; c->satellites = sats; c->signal = signal; c->next = 1U;
        c->updated = now;
    }
    if (page != c->next || pages != c->pages || sats != c->satellites ||
        (uint32_t)(now - c->updated) > 5000U) return;
    for (unsigned i = 0U; i < groups; ++i) {
        uint8_t cn;
        const char *v = f[7U + i * 4U];
        if (!*v) continue;
        if (!parse_uint8(v, 99U, &cn)) { c->next = 0U; return; }
        if (cn != 0U && signal == c->signal) {
            c->sum += cn; ++c->count;
            if (cn > c->maximum) c->maximum = cn;
        }
    }
    c->next = (uint8_t)(page + 1U);
    if (page == pages) {
        c->next = 255U; c->updated = now; /* complete cycle marker */
        ++s_diag.gsv_complete;
    }
}

bool gps_get_quality(gps_quality_t *out)
{
    unsigned sum = 0U, count = 0U, maximum = 0U;
    uint32_t youngest = 5001U;
    memset(out, 0, sizeof(*out));
    for (unsigned i = 0U; i < 3U; ++i) {
        const gsv_cycle_t *c = &s_gsv[i];
        if (c->next != 255U || (uint32_t)(TICK_MS() - c->updated) > 5000U) continue;
        /* Mixed GN summaries overlap per-constellation reports. */
        if (i == 2U && count != 0U) continue;
        uint32_t age = (uint32_t)(TICK_MS() - c->updated);
        if (age < youngest) { youngest = age; out->sequence = c->updated; }
        sum += c->sum; count += c->count;
        if (c->maximum > maximum) maximum = c->maximum;
    }
    if (count == 0U) return false;
    out->satellites = (uint8_t)(count > 255U ? 255U : count);
    out->average = (uint8_t)(sum / count); out->maximum = (uint8_t)maximum;
    return true;
}

bool gps_quality_fix_fresh(void)
{
    return s_gps.valid && s_gps.fix_quality != 0U &&
           (uint32_t)(TICK_MS() - s_gps.last_update_ms) <= 5000U &&
           (uint32_t)(TICK_MS() - s_gga_ms) <= 5000U;
}

/* ── Dispatch NMEA sentence ───────────────────────────────────────────────── */
static void __attribute__((noinline)) dispatch_nmea(char *sentence)
{
    nmea_parse_result_t result;
    ++s_diag.sentences;
    if (s_trace_remaining != 0U) {
        if ((uint32_t)(TICK_MS() - s_trace_started) <= 5000U) {
            --s_trace_remaining;
            dbg_printf("[NMEA] %s", sentence);
        } else s_trace_remaining = 0U;
    }
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
    } else if (strncmp(type, "GSV,", 4) == 0) {
        ++s_diag.gsv_seen;
        parse_gsv(sentence);
        return;
    } else return;
    if (result == NMEA_PARSE_OK) ++s_diag.parsed;
    else if (result == NMEA_PARSE_NO_FIX) ++s_diag.no_fix;
    else ++s_diag.format_fail;
}

static uint8_t s_ack_rx[8];
static volatile uint8_t s_ack_mailbox[8];
static volatile uint32_t s_ack_sequence;
static uint16_t s_binary_pos, s_binary_total;
static uint32_t s_binary_tick;

uint32_t gps_agnss_ack_sequence(void) { return s_ack_sequence; }
bool gps_agnss_take_ack(uint32_t *sequence,uint8_t frame[10])
{
    uint32_t before=s_ack_sequence;
    if(!sequence || !frame || before==*sequence || (before&1U))return false;
    frame[0]=0xf1;frame[1]=0xd9;
    for(unsigned i=0;i<8;i++)frame[i+2]=s_ack_mailbox[i];
    if(before!=s_ack_sequence)return false;
    *sequence=before;return true;
}

/* Bounded byte handoff only: no checksum scan, UART TX, or state-machine
 * progress in the ISR. Skip entire non-ACK binary frames, including payload
 * bytes resembling ACK sync. A stalled/truncated frame can resync after gap. */
static void agnss_rx_byte(uint8_t b)
{
    uint32_t now=TICK_MS();
    if((uint32_t)(now-s_binary_tick)>100U)s_binary_pos=0;
    s_binary_tick=now;
    if(!s_binary_pos){if(b==0xf1){s_binary_pos=1;}return;}
    if(s_binary_pos==1 && b!=0xd9){s_binary_pos=b==0xf1?1:0;return;}
    if(s_binary_pos>=2 && s_binary_pos<10)s_ack_rx[s_binary_pos-2]=b;
    ++s_binary_pos;
    if(s_binary_pos==6) {
        uint32_t total=(uint32_t)s_ack_rx[2]+((uint32_t)s_ack_rx[3]<<8)+8U;
        if(total>4096U){s_binary_pos=0;return;}
        s_binary_total=(uint16_t)total;
    }
    if(s_binary_pos>=8 && s_binary_pos==s_binary_total) {
        if(s_binary_total==10 && s_ack_rx[0]==5 && s_ack_rx[1]<=1) {
            ++s_ack_sequence;
            for(unsigned i=0;i<8;i++)s_ack_mailbox[i]=s_ack_rx[i];
            ++s_ack_sequence;
        }
        s_binary_pos=0;
    }
}

/* ── Called from UART4 RX interrupt ──────────────────────────────────────── */
void gps_rx_isr(uint8_t byte)
{
    agnss_rx_byte(byte);
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
static void gps_configure_output(void)
{
    /* ALLYSTAR V2.3.6 section 5.4.2: CFG-MSG, F0 NMEA group.
     * GGA=00, GSV=04, RMC=05; period=1. Volatile settings only. */
    static const uint8_t ids[] = {0x00U, 0x04U, 0x05U};
    for (unsigned i = 0U; i < sizeof(ids); ++i) {
        uint8_t frame[] = {0xF1U,0xD9U,0x06U,0x01U,0x03U,0x00U,0xF0U,0U,1U,0U,0U};
        frame[7] = ids[i];
        for (unsigned j = 2U; j < 9U; ++j) {
            frame[9] += frame[j]; frame[10] += frame[9];
        }
        if (gps_send_raw(frame, sizeof(frame)) != 0) {
            dbg_printf("[GPS] CFG-MSG TX failed\r\n");
            return;
        }
    }
}

void gps_init(void)
{
    s_binary_pos=0;s_binary_total=0;s_ack_sequence=0;
    memset(&s_gps, 0, sizeof(s_gps));
    memset(s_gsv, 0, sizeof(s_gsv));
    memset(&s_last_trusted, 0, sizeof(s_last_trusted));
    s_last_trusted_valid = false;
    memset((void *)&s_diag, 0, sizeof(s_diag));
    s_trace_remaining = 0U;
    s_nmea_pos = 0U;
    s_nmea_head = 0U;
    s_nmea_tail = 0U;
    s_nmea_count = 0U;
    s_nmea_drop = false;
    /* TAU804M: retain GGA/RMC and enable GSV at 1 Hz for RF quality. */
    delay_ms(500);
    gps_configure_output();
}

void gps_enable(bool en)
{
    s_enabled = en;
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

/* SysTick runs both awake and in shallow WFI. Keep fractional milliseconds
 * between calls; STOP1's stopped interval is added separately from the RTC. */
static void retained_clock_advance_awake(void)
{
    uint32_t elapsed_seconds;
    if (s_last_trusted.year < 2000U) return;
    elapsed_seconds = (uint32_t)(TICK_MS() - s_last_trusted_tick_ms) / 1000U;
    if (elapsed_seconds == 0U) return;
    gps_advance_last_trusted_seconds(elapsed_seconds);
    s_last_trusted_tick_ms += elapsed_seconds * 1000U;
}

void gps_process(void)
{
    retained_clock_advance_awake();
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
    return gps_capture_last_trusted_snapshot(&s_gps);
}

bool gps_capture_last_trusted_snapshot(const gps_data_t *snapshot)
{
    uint32_t now = TICK_MS();

    if (snapshot == NULL) return false;
    if (!snapshot->valid || snapshot->fix_quality == 0U ||
        (uint32_t)(now - snapshot->last_update_ms) > 5000U ||
        fabs(snapshot->lat) > 90.0 ||
        fabs(snapshot->lon) > 180.0 ||
        (snapshot->lat == 0.0 && snapshot->lon == 0.0) ||
        snapshot->year < 2000U || snapshot->month < 1U || snapshot->month > 12U ||
        snapshot->day < 1U || snapshot->day > 31U || snapshot->hour > 23U ||
        snapshot->minute > 59U || snapshot->second > 59U) {
        return false;
    }
    /* Never let the retained clock run backwards.  While asleep this snapshot's
     * clock is pushed forward by gps_advance_last_trusted_seconds() on every
     * STOP1 wake, so a live fix whose own timestamp is older than the advanced
     * value would rewind reported time.  A field capture showed the retained
     * stamp going 06:41:17 -> 06:41:06 when ACC bounce drove repeated sleep
     * entries.  Position is still refreshed; only an older clock is refused. */
    retained_clock_advance_awake();
    if (s_last_trusted_valid &&
        !retained_clock_is_newer(snapshot->year, snapshot->month, snapshot->day,
                                 snapshot->hour, snapshot->minute, snapshot->second)) {
        return false;
    }
    s_last_trusted.lat_e7 = (int32_t)(snapshot->lat * 10000000.0);
    s_last_trusted.lon_e7 = (int32_t)(snapshot->lon * 10000000.0);
    s_last_trusted.speed_x10 = snapshot->speed_kmh <= 0.0f ? 0U :
        snapshot->speed_kmh >= 6553.5f ? 65535U : (uint16_t)(snapshot->speed_kmh * 10.0f);
    s_last_trusted.heading_deg = snapshot->heading >= 359.0f ? 359U :
        snapshot->heading < 0.0f ? 0U : (uint16_t)snapshot->heading;
    s_last_trusted.altitude_m = snapshot->altitude_m <= -32768.0f ? -32768 :
        snapshot->altitude_m >= 32767.0f ? 32767 : (int16_t)snapshot->altitude_m;
    s_last_trusted.year = snapshot->year;
    s_last_trusted.month = snapshot->month;
    s_last_trusted.day = snapshot->day;
    s_last_trusted.hour = snapshot->hour;
    s_last_trusted.minute = snapshot->minute;
    s_last_trusted.second = snapshot->second;
    s_last_trusted.fix_quality = snapshot->fix_quality;
    s_last_trusted.satellites = snapshot->satellites;
    s_last_trusted_valid = true;
    s_last_trusted_tick_ms = snapshot->last_update_ms;
    return true;
}

bool gps_get_last_trusted(gps_data_t *out)
{
    if (out == NULL || !s_last_trusted_valid) return false;
    retained_clock_advance_awake();
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

    if (s_last_trusted.year < 2000U || elapsed_seconds == 0U)
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
    if (year < 2000U || month < 1U || month > 12U ||
        day < 1U || day > 31U || hour > 23U || minute > 59U || second > 59U)
        return;
    s_last_trusted.year = year;
    s_last_trusted.month = month;
    s_last_trusted.day = day;
    s_last_trusted.hour = hour;
    s_last_trusted.minute = minute;
    s_last_trusted.second = second;
    s_last_trusted_tick_ms = TICK_MS();
}

void gps_get_unfixed_report(gps_data_t *out)
{
    retained_clock_advance_awake();
    memset(out, 0, sizeof(*out));
    out->year = s_last_trusted.year;
    out->month = s_last_trusted.month;
    out->day = s_last_trusted.day;
    out->hour = s_last_trusted.hour;
    out->minute = s_last_trusted.minute;
    out->second = s_last_trusted.second;
}

void gps_resume_after_wake(void)
{
    /* STOP1 leaves the UART configuration intact.  Re-request GGA/GSV/RMC
     * output only; gps_init() would erase the retained STOP1 snapshot. */
    gps_configure_output();
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
