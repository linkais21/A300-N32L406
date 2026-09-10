#!/usr/bin/env python3
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "jt808.h"
#include "flash_config.h"
#include "gps.h"
#include "blind_zone.h"
#include "tcp_manager.h"
#include "jt808_session.h"
#include "jt808_terminal_info.h"
#include "work_mode.h"

volatile uint32_t g_tick_ms;
static device_config_t cfg;
static gps_data_t gps;
static bool open_ch[4];
static uint32_t generation[4];
static uint8_t last_frame[4][1024];
static uint16_t last_length[4];
static unsigned sends[4];
static unsigned auth_clear_calls[4];
static unsigned auth_store_calls[4];
static bool fail_auth_store;
static bool fail_send[4];
static bool ambiguous_send[4];
static bool s_last_ambiguous;
static bool reenter_send;
static int reenter_result;
static work_mode_state_t work_state = WORK_MODE_REALTIME;
static jt808_terminal_info_result_t terminal_info_result =
    JT808_TERMINAL_INFO_INVALID_ICCID;

device_config_t *cfg_get(void) { return &cfg; }
bool cfg_store_candidate(const device_config_t *candidate) { cfg = *candidate; return true; }
cfg_store_result_t cfg_set_pid_result(const char pid[CFG_PID_LEN])
{ memcpy(cfg.pid, pid, CFG_PID_LEN); return CFG_STORE_OK; }
bool cfg_set_auth_code(uint8_t channel, const char *code) {
    char *target = channel == 0U ? cfg.auth_code : channel == 3U ? cfg.backup_auth_code : 0;
    if (!target || strlen(code) >= CFG_AUTH_LEN) return false;
    ++auth_store_calls[channel];
    if (fail_auth_store) return false;
    if (code[0] == '\0') ++auth_clear_calls[channel];
    memset(target, 0, CFG_AUTH_LEN); memcpy(target, code, strlen(code)); return true;
}
void cfg_save(void) {}
void ec800m_get_imei(char *out, uint8_t size) { (void)size; strcpy(out, "123456789012345"); }
void ec800m_get_iccid(char *out, uint8_t size) { (void)size; strcpy(out, "89860412102500000001"); }
bool ec800m_is_ready(void) { return true; }
void ec800m_register_recv(ec800m_recv_cb_t cb) { (void)cb; }
int ec800m_tcp_send(uint8_t channel, const uint8_t *data, uint16_t length) {
    assert(channel == 0U || channel == 3U); assert(length <= sizeof(last_frame[0]));
    memcpy(last_frame[channel], data, length); last_length[channel] = length; ++sends[channel];
    s_last_ambiguous = ambiguous_send[channel];
    if (reenter_send) { reenter_send=false; reenter_result=jt808_send_heartbeat(); }
    return fail_send[channel] ? -1 : 0;
}
bool ec800m_tcp_send_was_ambiguous(void) { return s_last_ambiguous; }
void ec800m_tcp_send_clear_ambiguous(void) { s_last_ambiguous = false; }
int ec800m_get_csq(void) { return 20; }
float adc_get_car_voltage(void) { return 13.05f; }
float adc_get_bat_voltage(void) { return 4.10f; }
bool tcp_manager_is_online(void) { return open_ch[0] || open_ch[3]; }
bool tcp_manager_ch_online(uint8_t channel) { return channel < 4U && open_ch[channel]; }
uint8_t tcp_manager_active_ch(void) { return open_ch[0] ? 0U : 3U; }
uint32_t tcp_manager_session_generation(uint8_t channel) { return generation[channel]; }
tcp_state_t ec800m_tcp_state(uint8_t channel) { return open_ch[channel] ? TCP_STATE_OPEN : TCP_STATE_CLOSED; }
const gps_data_t *gps_get_data(void) { return &gps; }
bool i2c_accel_is_moving(void) { return false; }
int GPIO_ReadInputDataBit(void *p, unsigned pin) { (void)p; (void)pin; return 0; }
void relay_set(bool cut) { (void)cut; }
void geofence_handle_jt808(const uint8_t *b, uint16_t l, uint16_t s) { (void)b;(void)l;(void)s; }
void jt808_params_handle_set(const uint8_t *b, uint16_t l, uint16_t s) { (void)b;(void)l;(void)s; }
void jt808_params_handle_query(const uint8_t *b, uint16_t l, uint16_t s) {
    static const uint8_t reply[] = {0x12U, 0x34U};
    (void)b;(void)l;jt808_send_raw(0x0104U,s,reply,sizeof(reply));
}
void jt808_params_handle_info_query(uint16_t s) {
    static const uint8_t reply[] = {0x56U, 0x78U};
    jt808_send_raw(0x0107U,s,reply,sizeof(reply));
}
jt808_terminal_info_result_t jt808_terminal_info_encode(
    uint8_t *body, uint16_t capacity, uint16_t *length) {
    if (terminal_info_result != JT808_TERMINAL_INFO_OK)
        return terminal_info_result;
    assert(body != 0 && length != 0 && capacity > 0U);
    body[0] = 0xA5U; *length = 1U;
    return JT808_TERMINAL_INFO_OK;
}
void blind_zone_replay_reset(void) {}
void blind_zone_replay_on_general_ack(uint16_t s, uint16_t m, uint8_t r) { (void)s;(void)m;(void)r; }
blind_zone_result_t blind_zone_append(const blind_zone_record_t *r) { (void)r; return BLIND_ZONE_BUSY; }
int dbg_printf(const char *fmt, ...) { (void)fmt; return 0; }
bool hw_acc_is_on(void) { return false; }
bool gps_get_last_trusted(gps_data_t *out) { (void)out; return false; }
void log_platform_on_first_online(void) {}
work_mode_state_t work_mode_state(void) { return work_state; }

static uint16_t decode(uint8_t channel, uint8_t *out) {
    uint16_t i, pos = 0U; assert(last_length[channel] >= 2U);
    assert(last_frame[channel][0] == 0x7eU && last_frame[channel][last_length[channel]-1U] == 0x7eU);
    for (i=1U; i+1U<last_length[channel]; ++i) {
        uint8_t b=last_frame[channel][i];
        if (b==0x7dU) { ++i; b=last_frame[channel][i]==1U?0x7dU:0x7eU; }
        out[pos++]=b;
    }
    return pos;
}
static uint16_t msg(uint8_t ch, uint16_t *sn, uint8_t *decoded, uint16_t *len) {
    *len=decode(ch,decoded); *sn=(uint16_t)((decoded[10]<<8)|decoded[11]);
    return (uint16_t)((decoded[0]<<8)|decoded[1]);
}
static void inject(uint8_t ch, uint16_t id, const uint8_t *body, uint16_t body_len) {
    uint8_t raw[256], framed[512], cs=0U; uint16_t p=0U,o=0U,i;
    raw[p++]=(uint8_t)(id>>8);raw[p++]=(uint8_t)id;raw[p++]=(uint8_t)(body_len>>8);raw[p++]=(uint8_t)body_len;
    memcpy(raw+p,(uint8_t[]){0x05,0x67,0x89,0x01,0x23,0x45},6U);p+=6U;
    raw[p++]=0x12U;raw[p++]=0x34U;memcpy(raw+p,body,body_len);p+=body_len;
    for(i=0U;i<p;++i) cs^=raw[i];
    raw[p++]=cs;framed[o++]=0x7eU;
    for(i=0U;i<p;++i){if(raw[i]==0x7eU){framed[o++]=0x7dU;framed[o++]=2U;}else if(raw[i]==0x7dU){framed[o++]=0x7dU;framed[o++]=1U;}else framed[o++]=raw[i];}
    framed[o++]=0x7eU;jt808_on_recv(ch,framed,o);
}
static void reg_resp(uint8_t ch,uint16_t serial,const char *auth) {
    uint8_t body[64];size_t n=strlen(auth);body[0]=(uint8_t)(serial>>8);body[1]=(uint8_t)serial;body[2]=0U;memcpy(body+3,auth,n);inject(ch,0x8100U,body,(uint16_t)(3U+n));
}
static void auth_resp(uint8_t ch,uint16_t serial,uint8_t result) {
    uint8_t body[5]={(uint8_t)(serial>>8),(uint8_t)serial,0x01U,0x02U,result};inject(ch,0x8001U,body,5U);
}
static void query(uint8_t ch,uint16_t id) { inject(ch,id,0,0U); }

int main(void) {
    jt808_terminal_t terminal;uint8_t d0[1024],d3[1024];uint16_t sn0,sn3,l0,l3;
    unsigned before0,before3;
    memset(&cfg,0,sizeof(cfg));strcpy(cfg.pid,"56789012345");cfg.heartbeat_s=60;cfg.report_moving_s=30;cfg.report_stopped_s=60;
    memset(&terminal,0,sizeof(terminal));memcpy(terminal.manufacturer_id,"CYHLL",5U);strcpy(terminal.terminal_model,"A300_406");
    open_ch[0]=open_ch[3]=true;generation[0]=1U;generation[3]=7U;
    jt808_init(&terminal);jt808_process();
    assert(sends[0]==1U && sends[3]==1U);
    assert(msg(0U,&sn0,d0,&l0)==0x0100U);assert(msg(3U,&sn3,d3,&l3)==0x0100U);
    assert(memcmp(d0+4,(uint8_t[]){0x05,0x67,0x89,0x01,0x23,0x45},6U)==0);
    assert(memcmp(d0+12,(uint8_t[]){0,0,0,0},4U)==0);
    assert(memcmp(d0+41,"9012345",7U)==0);

    reg_resp(0U,sn3,"WRONG");assert(sends[0]==1U && cfg.auth_code[0]=='\0');
    reg_resp(0U,sn0,"MAIN-AUTH");
    assert(cfg.auth_code[0]=='\0' && sends[0]==1U && auth_store_calls[0]==0U);
    reg_resp(0U,sn0,"DUPLICATE");
    assert(cfg.auth_code[0]=='\0' && sends[0]==1U && auth_store_calls[0]==0U);
    jt808_process();assert(strcmp(cfg.auth_code,"MAIN-AUTH")==0);assert(auth_store_calls[0]==1U);
    assert(sends[0]==2U);assert(msg(0U,&sn0,d0,&l0)==0x0102U);
    reg_resp(3U,sn3,"BACK-AUTH");assert(cfg.backup_auth_code[0]=='\0' && sends[3]==1U);
    jt808_process();assert(strcmp(cfg.backup_auth_code,"BACK-AUTH")==0);assert(sends[3]==2U);assert(msg(3U,&sn3,d3,&l3)==0x0102U);
    auth_resp(0U,(uint16_t)(sn0+1U),0U);assert(!jt808_channel_online(0U));
    auth_resp(0U,sn0,0U);assert(jt808_channel_online(0U));assert(!jt808_channel_online(3U));
    auth_resp(3U,sn3,0U);assert(jt808_channel_online(3U));assert(jt808_online_mask()==0x09U);

    /* Changing only the primary endpoint invalidates only its in-memory
       credential/session.  The backup stays online while primary registers. */
    before0=sends[0];before3=sends[3];
    jt808_reset_endpoint_auth(JT808_ENDPOINT_MAIN_MASK);jt808_process();
    assert(sends[0]==before0+1U && sends[3]==before3);
    assert(msg(0U,&sn0,d0,&l0)==0x0100U);assert(jt808_channel_online(3U));
    reg_resp(0U,sn0,"MAIN-AUTH-2");jt808_process();
    assert(msg(0U,&sn0,d0,&l0)==0x0102U);auth_resp(0U,sn0,0U);
    assert(jt808_online_mask()==0x09U);

    /* Live 0x0200 uses the complete 67-byte A300 extension profile. */
    gps.lat=31.2057615;gps.lon=121.57613125;gps.altitude_m=78.5f;
    gps.speed_kmh=25.7f;gps.heading=15.0f;gps.fix_quality=1U;gps.satellites=9U;
    gps.hdop=1.3f;gps.year=2026U;gps.month=9U;gps.day=1U;
    gps.hour=8U;gps.minute=2U;gps.second=17U;gps.valid=true;gps.last_update_ms=g_tick_ms;
    cfg.mileage_m=21600U;
    before0=sends[0];before3=sends[3];jt808_process();
    assert(sends[0]==before0+1U && sends[3]==before3+1U);
    assert(msg(0U,&sn0,d0,&l0)==0x0200U);assert(msg(3U,&sn3,d3,&l3)==0x0200U);
    assert(memcmp(d0+16U,(uint8_t[]){0x00U,0x08U,0x00U,0x02U},4U)==0);
    assert(memcmp(d3+16U,(uint8_t[]){0x00U,0x08U,0x00U,0x02U},4U)==0);
    jt808_trigger_alarm(ALM_OVERSPEED);
    fail_send[3]=true;before0=sends[0];before3=sends[3];
    assert(jt808_send_location_work_mode(ALM_OVERSPEED,false)!=0);
    assert(sends[0]==before0+1U && sends[3]==before3+1U);
    assert(msg(0U,&sn0,d0,&l0)==0x0200U);
    assert(memcmp(d0+12U,(uint8_t[]){0x00U,0x00U,0x00U,0x02U},4U)==0);
    fail_send[3]=false;
    assert(jt808_send_location_work_mode(ALM_OVERSPEED,false)==0);
    assert(jt808_send_location_to(0U,&gps)==0);
    assert(msg(0U,&sn0,d0,&l0)==0x0200U);
    assert(memcmp(d0+12U,(uint8_t[]){0x00U,0x00U,0x00U,0x00U},4U)==0);
    before0=sends[0];before3=sends[3];g_tick_ms+=30001U;gps.last_update_ms=g_tick_ms;
    jt808_process();
    assert(sends[0]==before0 && sends[3]==before3);
    assert(jt808_send_location_work_mode(0U,false)==0);
    assert(sends[0]==before0+1U && sends[3]==before3+1U);
    fail_send[0]=fail_send[3]=true;ambiguous_send[0]=ambiguous_send[3]=true;
    assert(jt808_send_location_work_mode(0U,false)==0);
    fail_send[0]=fail_send[3]=false;ambiguous_send[0]=ambiguous_send[3]=false;
    assert(jt808_send_location_to(0U,&gps)==0);
    assert(msg(0U,&sn0,d0,&l0)==0x0200U);
    assert((uint16_t)(((d0[2]&0x03U)<<8)|d0[3])==67U);
    assert(l0==80U); /* 12-byte header + 67-byte body + checksum */
    cfg.gmt_sign=1;cfg.gmt_hour=5U;cfg.gmt_min=30U;
    gps.year=2024U;gps.month=2U;gps.day=29U;
    gps.hour=20U;gps.minute=15U;gps.second=16U;
    assert(jt808_send_location_to(0U,&gps)==0);
    assert(msg(0U,&sn0,d0,&l0)==0x0200U);
    assert(memcmp(d0+12U+22U,(uint8_t[]){0x24U,0x03U,0x01U,0x01U,0x45U,0x16U},6U)==0);
    cfg.gmt_sign=-1;cfg.gmt_hour=12U;cfg.gmt_min=59U;
    gps.year=2026U;gps.month=1U;gps.day=1U;
    gps.hour=0U;gps.minute=30U;gps.second=15U;
    assert(jt808_send_location_to(0U,&gps)==0);
    assert(msg(0U,&sn0,d0,&l0)==0x0200U);
    assert(memcmp(d0+12U+22U,(uint8_t[]){0x25U,0x12U,0x31U,0x11U,0x31U,0x15U},6U)==0);
    {
        const uint8_t *body=d0+12U;
        uint16_t p=28U;
        assert(body[p++]==0x01U && body[p++]==0x04U);
        assert(memcmp(body+p,(uint8_t[]){0x00,0x00,0x00,0xD8},4U)==0);p+=4U;
        assert(body[p++]==0x03U && body[p++]==0x02U);
        assert(body[p++]==0x01U && body[p++]==0x01U);
        assert(body[p++]==0x30U && body[p++]==0x01U && body[p++]==20U);
        assert(body[p++]==0x31U && body[p++]==0x01U && body[p++]==9U);
        assert(body[p++]==0x61U && body[p++]==0x02U);
        assert(body[p++]==0x05U && body[p++]==0x19U);
        assert(body[p++]==0xECU && body[p++]==0x05U);
        assert(body[p++]==0x00U && body[p++]==88U);
        assert(body[p++]==0x00U && body[p++]==41U && body[p++]==0U);
        assert(body[p++]==0xE3U && body[p++]==0x0AU);
        assert(body[p++]==0x01U && body[p++]==0xF4U); /* latitude tail 500 */
        assert(body[p++]==0x00U && body[p++]==0xFAU); /* longitude tail 250 */
        assert(body[p++]==0x01U && body[p++]==0xF4U); /* altitude tail 500 */
        assert(body[p++]==1U && body[p++]==9U);
        assert(body[p++]==0x00U && body[p++]==13U);
        assert(p==67U);
    }

    /* A queued auth belongs to one link generation and cannot cross reconnect. */
    open_ch[0]=false;jt808_process();open_ch[0]=true;++generation[0];
    jt808_process();assert(msg(0U,&sn0,d0,&l0)==0x0102U);
    auth_resp(0U,sn0,1U);g_tick_ms+=5000U;jt808_process();

    {
        unsigned before0=sends[0],before3=sends[3];
        query(3U,0x8104U);
        assert(sends[0]==before0 && sends[3]==before3+1U);
        assert(msg(3U,&sn3,d3,&l3)==0x0104U);
        before0=sends[0];before3=sends[3];
        query(3U,0x8107U);
        assert(sends[0]==before0 && sends[3]==before3+1U);
        assert(msg(3U,&sn3,d3,&l3)==0x0107U);
    }

    open_ch[0]=false;jt808_process();assert(!jt808_channel_online(0U));assert(jt808_channel_online(3U));
    open_ch[0]=true;++generation[0];
    jt808_process();assert(msg(0U,&sn0,d0,&l0)==0x0102U);
    auth_resp(0U,sn0,1U);
    before0=sends[0];g_tick_ms+=4999U;jt808_process();assert(sends[0]==before0);
    ++g_tick_ms;jt808_process();assert(sends[0]==before0+1U);assert(msg(0U,&sn0,d0,&l0)==0x0102U);
    auth_resp(0U,sn0,1U);
    before0=sends[0];g_tick_ms+=5000U;jt808_process();assert(sends[0]==before0+1U);assert(msg(0U,&sn0,d0,&l0)==0x0102U);
    auth_resp(0U,sn0,1U);
    assert(auth_clear_calls[0]==1U && auth_clear_calls[3]==0U);
    assert(cfg.auth_code[0]=='\0' && strcmp(cfg.backup_auth_code,"BACK-AUTH")==0);
    assert(jt808_channel_online(3U));
    before0=sends[0];g_tick_ms+=59999U;jt808_process();assert(sends[0]==before0);
    ++g_tick_ms;jt808_process();assert(sends[0]==before0+1U);assert(msg(0U,&sn0,d0,&l0)==0x0100U);

    memset(&cfg,0,sizeof(cfg));strcpy(cfg.pid,"56789012345");
    cfg.heartbeat_s=60U;cfg.report_moving_s=30U;cfg.report_stopped_s=60U;
    memset(sends,0,sizeof(sends));memset(open_ch,0,sizeof(open_ch));
    open_ch[0]=true;++generation[0];fail_send[0]=true;g_tick_ms=200000U;
    jt808_init(&terminal);jt808_process();assert(sends[0]==1U);
    jt808_process();assert(sends[0]==1U);
    g_tick_ms+=4999U;jt808_process();assert(sends[0]==1U);
    ++g_tick_ms;jt808_process();assert(sends[0]==2U);
    fail_send[0]=false;
    /* A pending registration token cannot survive a link generation change. */
    memset(&cfg,0,sizeof(cfg));strcpy(cfg.pid,"56789012345");
    memset(sends,0,sizeof(sends));memset(open_ch,0,sizeof(open_ch));
    open_ch[0]=true;++generation[0];g_tick_ms+=60000U;
    jt808_init(&terminal);jt808_process();assert(msg(0U,&sn0,d0,&l0)==0x0100U);
    before0=auth_store_calls[0];
    reg_resp(0U,sn0,"STALE-AUTH");assert(sends[0]==1U);
    ++generation[0];jt808_process();
    assert(cfg.auth_code[0]=='\0' && auth_store_calls[0]==before0);
    assert(sends[0]==2U && msg(0U,&sn0,d0,&l0)==0x0100U);

    /* Reentrant TX is rejected while the shared workspace is owned. */
    reenter_send=true;reenter_result=0;
    assert(jt808_send_register_to(0U)==0);assert(reenter_result==-1);

    /* Flash failure neither updates RAM auth nor sends AUTH from RX/main loop. */
    memset(&cfg,0,sizeof(cfg));strcpy(cfg.pid,"56789012345");
    memset(sends,0,sizeof(sends));memset(open_ch,0,sizeof(open_ch));
    open_ch[0]=true;++generation[0];fail_auth_store=true;g_tick_ms+=60000U;
    jt808_init(&terminal);jt808_process();assert(msg(0U,&sn0,d0,&l0)==0x0100U);
    reg_resp(0U,sn0,"NO-COMMIT");assert(sends[0]==1U && cfg.auth_code[0]=='\0');
    jt808_process();assert(sends[0]==1U && cfg.auth_code[0]=='\0');
    fail_auth_store=false;

    /* An ambiguous send failure ("SEND OK" wait timeout: bytes already on
       the wire, outcome unknown) must still let a late genuine ACK bring
       the channel online -- not be treated as a certain failure that wipes
       pending_valid and forces a resend/backoff cycle. */
    memset(&cfg,0,sizeof(cfg));strcpy(cfg.pid,"56789012345");
    strcpy(cfg.auth_code,"GOOD-AUTH");
    cfg.heartbeat_s=60U;cfg.report_moving_s=30U;cfg.report_stopped_s=60U;
    memset(sends,0,sizeof(sends));memset(open_ch,0,sizeof(open_ch));
    open_ch[0]=true;++generation[0];g_tick_ms+=60000U;
    ambiguous_send[0]=true;fail_send[0]=true;
    jt808_init(&terminal);jt808_process();
    assert(sends[0]==1U);assert(msg(0U,&sn0,d0,&l0)==0x0102U);
    ambiguous_send[0]=false;fail_send[0]=false;
    auth_resp(0U,sn0,0U);
    assert(jt808_channel_online(0U));

    /* Same guarantee on the REGISTER path (channel 3, no stored auth yet):
       an ambiguous REGISTER send must not discard the pending token before
       the platform's REGISTER_RESP with the matching serial arrives. */
    memset(&cfg,0,sizeof(cfg));strcpy(cfg.pid,"56789012345");
    cfg.heartbeat_s=60U;cfg.report_moving_s=30U;cfg.report_stopped_s=60U;
    memset(sends,0,sizeof(sends));memset(open_ch,0,sizeof(open_ch));
    open_ch[3]=true;++generation[3];g_tick_ms+=60000U;
    ambiguous_send[3]=true;fail_send[3]=true;
    jt808_init(&terminal);jt808_process();
    assert(sends[3]==1U);assert(msg(3U,&sn3,d3,&l3)==0x0100U);
    ambiguous_send[3]=false;fail_send[3]=false;
    reg_resp(3U,sn3,"NEW-AUTH");
    assert(sends[3]==1U && cfg.backup_auth_code[0]=='\0');
    jt808_process();
    assert(strcmp(cfg.backup_auth_code,"NEW-AUTH")==0);

    /* CAR remains UTF-8 in config/replies, but 0x0100 requires GBK on wire.
       The runtime profile must also retain the full 15-byte config value. */
    memset(&cfg,0,sizeof(cfg));strcpy(cfg.pid,"56789012345");
    memset(sends,0,sizeof(sends));memset(open_ch,0,sizeof(open_ch));
    open_ch[0]=true;++generation[0];g_tick_ms+=60000U;
    jt808_reset_endpoint_auth(JT808_ENDPOINT_MAIN_MASK |
                              JT808_ENDPOINT_BACKUP_MASK);
    jt808_init(&terminal);
    jt808_set_terminal_profile(NULL,"\xe4\xba\xac" "ABCDEFGHIJKL");
    jt808_process();assert(sends[0]==1U);assert(msg(0U,&sn0,d0,&l0)==0x0100U);
    assert(memcmp(d0+12U+37U,
                  (uint8_t[]){0xbeU,0xa9U,'A','B','C','D','E','F','G','H','I','J','K','L'},
                  14U)==0);
    assert((uint16_t)(((d0[2]&0x03U)<<8)|d0[3])==51U);

    assert(sizeof(jt808_session_t)*2U<128U);
    return 0;
}
'''

def compiler():
    cc=os.environ.get("CC") or shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    if cc:return cc
    for d in os.environ.get("PATH","").split(os.pathsep):
        if "WinLibs" in d:return str(Path(d.strip('"'))/"gcc.exe")
    return None

def main():
    cc=compiler()
    if not cc: print("test_jt808_dual_session: FAIL (host compiler required)");return 1
    with tempfile.TemporaryDirectory(prefix="jt808_dual_") as directory:
        t=Path(directory);h=t/"h.c";b=t/"h.exe";h.write_text(HARNESS,encoding="ascii")
        (t/"n32l40x.h").write_text("#ifndef N32L40X_H\n#define N32L40X_H\n#define GPIOA ((void*)0)\n#define GPIO_PIN_12 12U\n#define Bit_RESET 0\nint GPIO_ReadInputDataBit(void*,unsigned);\n#endif\n",encoding="ascii")
        cmd=[cc,"-std=c99","-Wall","-Wextra","-Werror","-I",str(t),"-I",str(ROOT/"include"),str(h),str(ROOT/"src/jt808.c"),str(ROOT/"src/jt808_session.c"),str(ROOT/"src/terminal_identity.c"),"-lm","-o",str(b)]
        x=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True)
        if x.returncode:print(x.stdout+x.stderr,end="");return x.returncode
        x=subprocess.run([str(b)],cwd=ROOT,capture_output=True,text=True)
        if x.returncode:print(x.stdout+x.stderr,end="");return x.returncode
    print("test_jt808_dual_session: PASS");return 0
if __name__=="__main__":sys.exit(main())
