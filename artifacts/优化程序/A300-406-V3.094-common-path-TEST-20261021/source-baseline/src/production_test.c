#include "production_test.h"
#include "config.h"
#include "n32l40x.h"
#include "hw_init.h"
#include "work_mode.h"
#include "debug_uart.h"
#include "adc_monitor.h"
#include "i2c_accel.h"
#include "relay.h"
#include "gps.h"
#include <string.h>

static volatile uint8_t s_acc_count;
static volatile bool s_acc_deb;
static volatile uint16_t s_sos_ms;
static volatile uint16_t s_sample_lease_ms;

void production_test_tick(void)
{
    if (s_sample_lease_ms == 0U) return;
    if (--s_sample_lease_ms == 0U) { s_acc_count = 0U; s_sos_ms = 0U; return; }
    bool acc = hw_acc_is_on();
    if (acc == s_acc_deb) s_acc_count = 0U;
    else if (++s_acc_count >= 50U) { s_acc_deb = acc; s_acc_count = 0U; }
    if (GPIO_ReadInputDataBit(SOS_PORT, SOS_PIN) != Bit_RESET) s_sos_ms = 0U;
    else if (s_sos_ms < 65535U) ++s_sos_ms;
}

bool production_test_command(const char *line)
{
    if (strcmp(line, "FACTORYCAP#") == 0) {
        dbg_printf("FACTORYCAP,VER=1,ACC=1,GSENSOR=1,VOLTAGE=1,RELAY=1,TTS=0,RS485=0,SOS=1,GNSS=1=Success!\r\n");
    } else if (strcmp(line, "ACCSTAT#") == 0) {
        dbg_printf("ACCSTAT,RAW=%u,DEB=%u,HW=1,LOGIC=%u=Success!\r\n",
                   (unsigned)hw_acc_is_on(), (unsigned)s_acc_deb,
                   (unsigned)work_mode_logical_acc());
    } else if (strcmp(line, "GSENSOR#") == 0) {
        accel_data_t a;
        if (!i2c_accel_read(&a)) dbg_printf("GSENSOR=Fail!READ_FAILED\r\n");
        else dbg_printf("GSENSOR,X=%d,Y=%d,Z=%d,INT=%u=Success!\r\n", a.x, a.y, a.z,
                        (unsigned)(GPIO_ReadInputDataBit(DA218E_INT1_PORT, DA218E_INT1_PIN) != Bit_RESET));
    } else if (strcmp(line, "STATUS#") == 0) {
        if (!adc_monitor_valid()) dbg_printf("STATUS=Fail!ADC_NOT_READY\r\n");
        else dbg_printf("STATUS,VCAR=%u,VBAT=%u,VALID=1=Success!\r\n",
                        (unsigned)(adc_get_car_voltage() * 1000.0f + 0.5f),
                        (unsigned)(adc_get_bat_voltage() * 1000.0f + 0.5f));
    } else if (strcmp(line, "SOSSTAT#") == 0) {
        bool down = GPIO_ReadInputDataBit(SOS_PORT, SOS_PIN) == Bit_RESET;
        uint16_t held = down ? s_sos_ms : 0U;
        dbg_printf("SOSSTAT,DOWN=%u,HOLD_MS=%u,LEVEL=%s,ACTIVE=%u=Success!\r\n",
                   (unsigned)down, held, down ? "LOW" : "HIGH", (unsigned)down);
    } else if (strcmp(line, "GNSSSTAT#") == 0 || strncmp(line, "GNSSSTAT,", 9U) == 0) {
        if (line[8] == ',') {
            /* Exactly two decimal digits and '#'; never accept trailing data. */
            if (strlen(line) != 12U || line[9] < '0' || line[9] > '9' ||
                line[10] < '0' || line[10] > '9' || line[11] != '#' ||
                !gps_set_quality_cn_threshold((uint8_t)((line[9]-'0')*10 + line[10]-'0'))) {
                dbg_printf("GNSSSTAT=Fail!INVALID_ARGUMENT\r\n");
                return true;
            }
        }
        const gps_data_t *g = gps_get_data();
        gps_quality_t q = {0};
        bool fresh = gps_quality_fix_fresh();
        (void)gps_get_quality(&q);
        float scaled_hdop = fresh && g->hdop > 0.0f && g->hdop < 100.0f ?
                            g->hdop * 1000.0f : 0.0f;
        unsigned hdop = (unsigned)scaled_hdop;
        /* Never round an over-limit reading down onto a passing boundary. */
        if (scaled_hdop > (float)hdop) ++hdop;
        dbg_printf("GNSSSTAT,FIX=%u,GPS=%u,HDOP=%u.%03u,CNSAT=%u,CNAVG=%u,CNMAX=%u,SEQ=%lu,CNTH=%u,CNGOOD=%u=Success!\r\n",
                   fresh ? g->fix_quality : 0U, fresh ? g->satellites : 0U,
                   hdop / 1000U, hdop % 1000U, q.satellites, q.average, q.maximum,
                   (unsigned long)q.sequence, q.cn_threshold, q.qualified);
    } else if (strcmp(line, "GNSSRAW#") == 0) {
        gps_trace_start();
        dbg_printf("GNSSRAW,MAX=32,WINDOW_MS=5000=Success!\r\n");
    } else if (strcmp(line, "GNSSDIAG#") == 0) {
        const volatile gps_diag_t *d = gps_get_diag();
        dbg_printf("GNSSDIAG,RX=%lu,GGA=%lu,RMC=%lu,GSV=%lu,COMPLETE=%lu,QUEUE_DROP=%lu,LENGTH_DROP=%lu,CHECKSUM=%lu,OVERRUN=%lu=Success!\r\n",
                   (unsigned long)d->rx_bytes, (unsigned long)d->gga,
                   (unsigned long)d->rmc, (unsigned long)d->gsv_seen,
                   (unsigned long)d->gsv_complete, (unsigned long)d->drop_queue,
                   (unsigned long)d->drop_length, (unsigned long)d->checksum_fail,
                   (unsigned long)d->overrun);
    } else if (strncmp(line, "RELAYTEST", 9U) == 0) {
        if (strcmp(line, "RELAYTEST,HIGH#") == 0) relay_test_high();
        else if (strcmp(line, "RELAYTEST,LOW#") == 0) {
            if (!relay_test_low()) {
                dbg_printf("RELAYTEST=Fail!BUSY\r\n");
                return true;
            }
        } else if (strcmp(line, "RELAYTEST,STATUS#") != 0) {
            dbg_printf("RELAYTEST=Fail!INVALID_ARGUMENT\r\n");
            return true;
        }
        bool state = relay_get();
        dbg_printf("RELAYTEST,OUT=%s,MCU=%u,PAD=%u,REMAIN_MS=%u=Success!\r\n",
                   state ? "LOW" : "HIGH", (unsigned)state,
                   (unsigned)(GPIO_ReadInputDataBit(RELAY_PORT, RELAY_PIN) != Bit_RESET),
                   (unsigned)relay_test_remaining());
    } else return false;
    /* Polling keeps diagnostics live; ordinary operation has no permanent
     * 1 kHz GPIO sampling after the factory tool disconnects. */
    if (s_sample_lease_ms == 0U) { s_acc_deb = hw_acc_is_on(); s_acc_count = 0U; }
    s_sample_lease_ms = 5000U;
    return true;
}
