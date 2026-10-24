"""Real JT808 parser -> F39 RESET -> deferred MCU reset (hardware stub only)."""
from pathlib import Path
import subprocess
import tempfile
import test_jt808_dual_session as dual

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = r'''
#include "at_config.h"
#include "f39_reply.h"
#include "sms_command.h"
#include "peripherals.h"
int log_platform_send_result(void) { return 0; }
void tcp_manager_reconnect_channels(uint8_t mask) { (void)mask; }
static unsigned resets;
static bool check_ack_order;
void NVIC_SystemReset(void) { ++resets; }
static void reset_send_probe(void) {
    if (check_ack_order) {
        unsigned before=resets;
        g_tick_ms+=1000;at_config_process();assert(resets==before);
    }
}
bool fota_request_check(void) { return true; }
uint32_t work_mode_sleep_monotonic_s(void) { return 0; }
void work_mode_config_changed(const device_config_t *c,uint32_t now) {(void)c;(void)now;}
void tcp_manager_reconnect(void) {}
void ec800m_restart_pdp(void) {}
void gnss_vendor_set_type(gnss_type_t t) {(void)t;}
void agnss_init(gnss_type_t t) {(void)t;}
uint16_t relay_test_remaining(void) { return 0; }
bool production_test_command(const char *s) {(void)s;return false;}
bool relay_get(void) { return false; }
bool gps_quality_fix_fresh(void) { return false; }
bool gps_get_quality(gps_quality_t *q) {(void)q;return false;}
bool gps_is_valid(void) { return false; }
void gps_send_cmd(const char *s) {(void)s;}
bool hw_acc_pin_high(void) { return true; }
int sms_send(const char *p,const char *t) {(void)p;(void)t;return 0;}
void sms_set_send_result_cb(sms_send_result_cb_t cb) {(void)cb;}

static void expect_ack(uint8_t ch,uint8_t result) {
    uint8_t b[1024];uint16_t sn,len;
    assert(msg(ch,&sn,b,&len)==0x0001U);
    assert(b[12]==0x12 && b[13]==0x34 && b[14]==0x81 && b[15]==0x05);
    assert(b[16]==result);
    assert(!memcmp(b+4,(uint8_t[]){0x05,0x67,0x89,0x01,0x23,0x45},6));
}
static void expire(void) {
    unsigned before=resets;
    at_config_process();assert(resets==before);
    g_tick_ms+=F39_RESET_DELAY_MS-1U;at_config_process();assert(resets==before);
    ++g_tick_ms;at_config_process();assert(resets==before+1U);
    at_config_process();assert(resets==before+1U);
}
int main(void) {
    jt808_terminal_t terminal={0};uint8_t decoded[1024],body[2]={4,0};
    uint16_t sn,len;unsigned before;
    strcpy(cfg.pid,"56789012345");cfg.gnss_type=GNSS_TYPE_TAU804M;
    cfg.heartbeat_s=600;cfg.report_moving_s=30;cfg.report_stopped_s=60;
    memcpy(terminal.manufacturer_id,"CYHLL",5);strcpy(terminal.terminal_model,"A300_406");
    at_config_init();open_ch[0]=open_ch[3]=true;generation[0]=1;generation[3]=7;
    jt808_init(&terminal);jt808_process();
    /* An open TCP connection without authentication cannot reset the MCU. */
    before=sends[0];inject(0,0x8105,body,1);assert(sends[0]==before);
    g_tick_ms+=1000;at_config_process();assert(!resets);
    for(unsigned ch=0;ch<=3;ch+=3) {
        assert(msg(ch,&sn,decoded,&len)==0x0100);
        reg_resp(ch,sn,"TEST-AUTH");jt808_process();
        assert(msg(ch,&sn,decoded,&len)==0x0102);auth_resp(ch,sn,0);
    }
    assert(jt808_online_mask()==9);
    test_rx_overlap();
    /* A truncated or corrupt frame cannot reset; a completed split frame can. */
    {
        uint8_t wire[]={0x7e,0x81,0x05,0,1,0x05,0x67,0x89,0x01,0x23,0x45,0x12,0x34,4,0,0x7e};
        for(unsigned i=1;i<14;i++) wire[14]^=wire[i];
        before=sends[0];wire[14]^=1;
        jt808_on_recv(0,wire,sizeof wire);assert(sends[0]==before);
        g_tick_ms+=1000;at_config_process();assert(!resets);wire[14]^=1;
        jt808_on_recv(0,wire,8);assert(sends[0]==before);
        g_tick_ms+=1000;at_config_process();assert(!resets);
        jt808_on_recv(0,wire+8,sizeof wire-8);expect_ack(0,0);expire();
    }
    for(unsigned ch=0;ch<=3;ch+=3) {
        check_ack_order=true;
        before=sends[3-ch];inject(ch,0x8105,body,1);expect_ack(ch,0);
        check_ack_order=false;
        assert(sends[3-ch]==before);expire();
    }
    /* Malformed bodies and unsupported controls never schedule a reset. */
    before=resets;
    query(0,0x8105);expect_ack(0,2);
    inject(0,0x8105,body,2);expect_ack(0,2);
    body[0]=3;inject(0,0x8105,body,1);expect_ack(0,3);body[0]=4;
    g_tick_ms+=1000;at_config_process();assert(resets==before);
    /* An ACK send failure still leaves a bounded reset, not an infinite wait. */
    fail_send[0]=true;inject(0,0x8105,body,1);expect_ack(0,0);expire();fail_send[0]=false;
    /* Repeated requests coalesce without pushing the original deadline back. */
    before=resets;inject(0,0x8105,body,1);expect_ack(0,0);
    g_tick_ms+=F39_RESET_DELAY_MS-1U;
    inject(3,0x8105,body,1);expect_ack(3,0);at_config_process();assert(resets==before);
    ++g_tick_ms;at_config_process();assert(resets==before+1);
    g_tick_ms+=1000;at_config_process();assert(resets==before+1);
    /* Deadline comparison also works across the millisecond counter wrap. */
    g_tick_ms=UINT32_MAX-50U;inject(0,0x8105,body,1);expect_ack(0,0);expire();
    /* The old session generation cannot trigger a reset after reconnect. */
    ++generation[0];before=sends[0];inject(0,0x8105,body,1);assert(sends[0]==before);
    before=resets;g_tick_ms+=1000;at_config_process();assert(resets==before);
    return 0;
}
'''


def main():
    source = dual.HARNESS[:dual.HARNESS.index('int main(void) {')] + SUPPORT
    source += '\n#define HOST_REAL_AT_CONFIG\n#include "' + (ROOT/'tools/tests/jt808_host_support.h').as_posix() + '"\n'
    source = 'static void reset_send_probe(void);\n' + source
    source = source.replace('    assert(channel == 0U || channel == 3U);',
                            '    reset_send_probe();\n    assert(channel == 0U || channel == 3U);')
    modules = ['jt808', 'jt808_session', 'terminal_identity', 'plate_encoding',
               'at_config', 'f39_command', 'f39_config_adapter', 'f39_reply', 'sms_command']
    with tempfile.TemporaryDirectory(prefix='terminal_reset_') as directory:
        path = Path(directory)
        (path / 'h.c').write_text(source, encoding='ascii')
        (path / 'n32l40x.h').write_text('#pragma once\n#define GPIOA ((void*)0)\n'
            '#define GPIO_PIN_12 12U\n#define Bit_RESET 0\n'
            'int GPIO_ReadInputDataBit(void*,unsigned);\nvoid NVIC_SystemReset(void);\n', encoding='ascii')
        subprocess.run([dual.compiler(), '-std=c99', '-Wall', '-Wextra', '-Werror',
                        '-I', str(path), '-I', str(ROOT / 'include'), str(path / 'h.c'),
                        *[str(ROOT / 'src' / (m + '.c')) for m in modules], '-lm',
                        '-o', str(path / 'h.exe')], check=True, timeout=60)
        subprocess.run([str(path / 'h.exe')], check=True, timeout=30)
    print('test_terminal_reset: PASS')


if __name__ == '__main__':
    main()
