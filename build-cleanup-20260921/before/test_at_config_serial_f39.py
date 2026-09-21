"""Contract for the F39 terminal command set over the debug serial console.

The terminal command spec lists three delivery paths: SMS, serial, and JT808
0x8300. This covers the serial one: bytes fed through at_config_feed() must run
the same F39 command set and echo the reply on the debug UART, while the legacy
console commands (VERSION, SERVER=, TIMER=, ...) keep working.
"""

import os
import pathlib
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]


def compiler():
    found = shutil.which("gcc")
    if found:
        return found
    base = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    candidates = list(base.glob("BrechtSanders.WinLibs*/mingw64/bin/gcc.exe"))
    candidates += list(pathlib.Path.home().glob("scoop/apps/gcc/current/bin/gcc.exe"))
    if candidates:
        return str(candidates[0])
    if os.environ.get("REQUIRE_GCC") == "1":
        raise RuntimeError("gcc is required but was not found")
    return None


HARNESS = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "at_config.h"
#include "f39_reply.h"
#include "gps.h"
#include "sms_command.h"
#include "peripherals.h"

static device_config_t config;
static unsigned saves, system_resets;
static unsigned ota_rechecks;
static unsigned ota_recheck_after_save;
static bool persist_ok = true;
static char ota_key[CFG_DEVICE_API_KEY_LEN];
static uint32_t refreshed_at_s;
static char console[1024];
static unsigned console_len;

volatile uint32_t g_tick_ms;
device_config_t *cfg_get(void) { return &config; }
bool cfg_store_candidate(const device_config_t *c) { saves++; if (!persist_ok) return false; config = *c; return true; }
bool fota_request_check(void) {
    ++ota_rechecks;
    ota_recheck_after_save = saves;
    memcpy(ota_key, config.device_api_key, sizeof ota_key);
    return true;
}
cfg_store_result_t cfg_set_pid_result(const char pid[CFG_PID_LEN])
{ memcpy(config.pid, pid, CFG_PID_LEN); return CFG_STORE_OK; }
void cfg_save(void) { }
void jt808_set_heartbeat_s(uint16_t s) { (void)s; }
void jt808_set_report_interval(uint16_t a, uint16_t b) { (void)a; (void)b; }
void jt808_set_server(const char *ip, uint16_t p, bool b) { (void)ip; (void)p; (void)b; }
void jt808_request_reregister(void) { }
void jt808_set_terminal_profile(const char *model, const char *plate) { (void)model; (void)plate; }
void jt808_reset_endpoint_auth(uint8_t mask) { (void)mask; }
uint32_t work_mode_sleep_monotonic_s(void) { return 1234U; }
void work_mode_config_changed(const device_config_t *c, uint32_t now_s)
{ (void)c; refreshed_at_s = now_s; }
void tcp_manager_reconnect(void) { }
void ec800m_restart_pdp(void) { }
void gnss_vendor_set_type(gnss_type_t t) { (void)t; }
void agnss_init(gnss_type_t t) { (void)t; }
void relay_set(bool on) { (void)on; }
uint16_t relay_test_remaining(void) { return 0U; }
static unsigned production_calls;
bool production_test_command(const char *line) {
    ++production_calls;
    return strcmp(line, "FACTORYCAP#") == 0;
}
bool relay_get(void) { return false; }
static bool quality_fresh;
bool gps_quality_fix_fresh(void) { return quality_fresh; }
bool gps_get_quality(gps_quality_t *q) { memset(q, 0, sizeof(*q)); if (quality_fresh) { q->satellites=8; q->average=38; q->maximum=44; } return quality_fresh; }
bool gps_is_valid(void) { return true; }
const gps_data_t *gps_get_data(void) { static gps_data_t g; g.valid = true; g.fix_quality=1; g.hdop=1.2f; g.satellites=8; return &g; }
void gps_send_cmd(const char *c) { (void)c; }
int GPIO_ReadInputDataBit(void *p, unsigned x) { (void)p; (void)x; return 1; }
/* Q9 inverts PA12, so a high pin means ACC OFF. */
bool hw_acc_is_on(void) { return false; }
bool hw_acc_pin_high(void) { return true; }
void ec800m_get_imei(char *b, uint8_t n) { if (n > 0) { strncpy(b, "123456789012345", n-1); b[n-1]=0; } }
void ec800m_get_iccid(char *b, uint8_t n) { if (n > 0) { strncpy(b, "89860492192080502719", n-1); b[n-1]=0; } }
int ec800m_get_csq(void) { return 20; }
void NVIC_SystemReset(void) { system_resets++; }
int sms_send(const char *p, const char *t) { (void)p; (void)t; return 0; }
void sms_set_send_result_cb(sms_send_result_cb_t cb) { (void)cb; }

/* Capture whatever the firmware prints on the debug UART. */
int dbg_printf(const char *fmt, ...) {
    va_list ap;
    int n;
    va_start(ap, fmt);
    n = vsnprintf(console + console_len, sizeof(console) - console_len, fmt, ap);
    va_end(ap);
    if (n > 0) console_len += (unsigned)n;
    return n;
}

static void line(const char *text) {
    console_len = 0U; console[0] = '\0';
    while (*text) at_config_feed((uint8_t)*text++);
    at_config_feed('\r');
    at_config_process();
}

int main(void) {
    memset(&config, 0, sizeof config);
    config.gnss_type = GNSS_TYPE_TAU804M;
    strcpy(config.terminal_model, "A300_406");
    strcpy(config.server_ip, "host"); config.server_port = 9000;
    strcpy(config.pid, "12345678901");
    config.heartbeat_s = 180; config.report_moving_s = 30; config.report_stopped_s = 180;
    config.vib_sens = 30; config.gpsbds_mode = 2; config.speed_limit_kmh = 120;
    config.gmt_sign = 1; config.gmt_hour = 8;
    at_config_init();

    line("FACTORYCAP#");
    assert(production_calls == 1U);
    assert(!at_config_execute_text_command((const uint8_t *)"FACTORYCAP#", 11U));
    assert(!at_config_execute_sms("10000", (const uint8_t *)"RELAYTEST,LOW#", 14U));
    assert(production_calls == 1U); /* no remote factory dispatch */

    /* A setter takes effect and is acknowledged on the console. Setters reply
       with the bare root ("VIBSENS=Success!"), matching every other setter in
       f39_reply.c's success() path rather than echoing the argument. */
    line("VIBSENS,20#");
    assert(strstr(console, "VIBSENS=Success!") != 0);
    assert(config.vib_sens == 20 && saves == 1);

    /* The framing '#' is optional over serial. */
    line("VIBSENS,40");
    assert(strstr(console, "VIBSENS=Success!") != 0);
    assert(config.vib_sens == 40);

    /* A query reports the stored value without writing anything. */
    saves = 0U;
    line("VIBSENS#");
    assert(strstr(console, "VIBSENS,40=Success!") != 0);
    assert(saves == 0U);

    /* Out-of-range input is refused and leaves the value alone. */
    line("VIBSENS,99#");
    assert(strstr(console, "Success!") == 0);
    assert(config.vib_sens == 40 && saves == 0U);

    /* Queries do echo the value, so this proves the setter above persisted. */
    line("VIBSENS#");
    assert(strstr(console, "VIBSENS,40=Success!") != 0);

    /* Other command groups reach the console too. */
    line("FREQ,60,300#");
    assert(strstr(console, "FREQ=Success!") != 0);
    assert(config.report_moving_s == 60 && config.report_stopped_s == 300);
    assert(refreshed_at_s == 1234U);

    line("PARAM#");
    assert(strstr(console, "PRO[JT808_2013]") != 0);
    assert(strstr(console, "ICCID[89860492192080502719]") != 0);
    assert(strstr(console, "MODEL[A300_406]") != NULL);
    assert(strstr(console, "FIX[0]HDOP[0.0]CNSAT[0]") != NULL);
    quality_fresh = true;
    line("PARAM#");
    assert(strstr(console, "FIX[1]HDOP[1.2]CNSAT[8]CNAVG[38]CNMAX[44]") != NULL);
    if (getenv("A300_V150_WIRE")) {
        FILE *f = fopen(getenv("A300_V150_WIRE"), "w");
        assert(f != NULL); fputs(console, f); fclose(f);
    }

    line("APN,CMIOT,,#");
    assert(strstr(console, "APN=Success!") != NULL);
    assert(!config.autoapn_en && strcmp(config.apn, "CMIOT") == 0);
    line("APN#");
    assert(strstr(console, "APN,CMIOT=Success!") != NULL);
    if (getenv("A300_V150_WIRE")) {
        FILE *f = fopen(getenv("A300_V150_WIRE"), "a");
        assert(f != NULL); fputs(console, f); fclose(f);
    }
    line("APN,CMIOT,user,#");
    assert(strstr(console, "APN=Success!") != NULL);
    line("APN#");
    assert(strstr(console, "APN,CMIOT=Success!") != NULL);
    assert(strstr(console, "user") == NULL);
    line("APN,CMIOT,,secret#");
    assert(strstr(console, "APN=Success!") != NULL);
    line("APN#");
    assert(strstr(console, "APN,CMIOT=Success!") != NULL);
    assert(strstr(console, "secret") == NULL);
    saves = 0U;
    line("APN,,,#");
    assert(strstr(console, "Success!") == NULL && saves == 0U);
    line("APN,CMIOT,,,extra#");
    assert(strstr(console, "Success!") == NULL && saves == 0U);
    persist_ok = false;
    line("APN,OTHER,,#");
    assert(strstr(console, "Success!") == NULL);
    assert(strcmp(config.apn, "CMIOT") == 0);
    persist_ok = true;

    line("APN,AUTO,,#");
    assert(strstr(console, "APN=Success!") != NULL && config.autoapn_en);
    assert(!config.apn[0] && !config.apn_user[0] && !config.apn_pass[0]);
    line("APN#");
    assert(strstr(console, "APN,AUTO=Success!") != NULL);
    saves = 0U;
    line("APN,AUTO,user,#");
    assert(strstr(console, "Success!") == NULL && saves == 0U);
    line("APN,AUTO,,secret#");
    assert(strstr(console, "Success!") == NULL && saves == 0U);
    line("APN,0,,#");
    assert(strstr(console, "APN=Success!") != NULL && config.autoapn_en);
    line("APN,CMIOT,,#");
    assert(strstr(console, "APN=Success!") != NULL && !config.autoapn_en);

    /* PID echoes the full 11-digit device id, as over SMS. */
    line("PID#");
    assert(strstr(console, "PID,12345678901=Success!") != 0);

    /* Legacy console commands still work: the F39 attempt must fall through
       rather than swallow the line. */
    line("VERSION");
    assert(strstr(console, "UNKNOWN") == 0);
    line("TIMER=45,90");
    assert(strstr(console, "OK") != 0);
    assert(config.report_moving_s == 45 && config.report_stopped_s == 90);
    assert(refreshed_at_s == 1234U);

    /* A genuinely unknown line is still reported as unknown. */
    line("NOSUCHCOMMAND");
    assert(strstr(console, "ERR:UNKNOWN CMD") != 0);

    /* Only a durable key update rearms OTA, after publishing the new config.
       Serial, SMS, and JT808 text ingress all use the default F39 binding. */
    saves = 0U;
    line("FKEY,mIxedCase-Key1234#");
    assert(strstr(console, "FKEY,CONFIGURED=1") != NULL);
    assert(ota_rechecks == 1U && ota_recheck_after_save == 1U);
    assert(strcmp(ota_key, "mIxedCase-Key1234") == 0);
    assert(strstr(console, ota_key) == NULL);
    line("FKEY?");
    assert(ota_rechecks == 1U && saves == 1U);
    line("FKEY,short#");
    assert(ota_rechecks == 1U && saves == 1U);
    persist_ok = false;
    line("FKEY,another-key123456#");
    assert(ota_rechecks == 1U && saves == 2U);
    assert(strcmp(config.device_api_key, ota_key) == 0);
    assert(strstr(console, "another-key123456") == NULL);
    persist_ok = true;
    {
        const char *sms_key = "FKEY,sms-key-123456789";
        const char *text_key = "FKEY,text-key-12345678";
        assert(at_config_execute_sms("13800000001", (const uint8_t *)sms_key,
                                     (uint16_t)strlen(sms_key)));
        assert(ota_rechecks == 2U && ota_recheck_after_save == 3U);
        assert(strcmp(ota_key, "sms-key-123456789") == 0);
        assert(at_config_execute_text_command((const uint8_t *)text_key,
                                              (uint16_t)strlen(text_key)));
        assert(ota_rechecks == 3U && ota_recheck_after_save == 4U);
        assert(strcmp(ota_key, "text-key-12345678") == 0);
    }

    /* RESET over serial schedules the restart rather than resetting inside
       the parser; at_config_process() performs it once the delay elapses. */
    system_resets = 0U;
    line("RESET#");
    assert(strstr(console, "RESET=Success!") != 0);
    assert(system_resets == 0U);
    g_tick_ms += F39_RESET_DELAY_MS + 1U;
    at_config_process();
    assert(system_resets == 1U);

    line("AGPS=ON");assert(config.agps_en==1 && strstr(console,"OK"));
    persist_ok=false;line("AGPS=OFF");assert(config.agps_en==1 && strstr(console,"ERR"));
    persist_ok=true;line("AGPS=OFF");assert(config.agps_en==0);
    line("AGPS=INVALID");assert(config.agps_en==0 && strstr(console,"ERR"));
    config.anglerep_en=0;
    line("ANGLEREP=ON");assert(config.anglerep_en==1 && strstr(console,"OK"));
    persist_ok=false;line("ANGLEREP=OFF");assert(config.anglerep_en==1 && strstr(console,"ERR:SAVE"));
    persist_ok=true;line("ANGLEREP=OFF");assert(config.anglerep_en==0 && strstr(console,"OK"));
    line("ANGLEREP=1");assert(config.anglerep_en==1);
    line("ANGLEREP=0");assert(config.anglerep_en==0);
    unsigned corner_saves=saves;
    line("ANGLEREP=INVALID");assert(config.anglerep_en==0 && strstr(console,"ERR:ARG"));
    line("ANGLEREP=ON,30,2");assert(config.anglerep_en==0 && strstr(console,"ERR:ARG"));
    line("ANGLEREP");assert(config.anglerep_en==0 && strstr(console,"ERR:ARG"));
    assert(saves==corner_saves);
    line("ANGLEREP=ON");line("ANGLEREP=ON");assert(config.anglerep_en==1);
    const char *legacy[]={"SOSALM","GMT","CELLAUTOGMT","GEOREP","MILEAGE","AUTOAPN","SENDS=1"};
    for(unsigned i=0;i<sizeof legacy/sizeof legacy[0];i++){line(legacy[i]);assert(strstr(console,"OK"));}
    line("SENDS");assert(strstr(console,"ERR"));

    return 0;
}
'''


def main() -> int:
    cc = compiler()
    if not cc:
        print("test_at_config_serial_f39: SKIP (no gcc)")
        return 0
    with tempfile.TemporaryDirectory(prefix="at_config_serial_") as directory:
        tmp = pathlib.Path(directory)
        src = tmp / "h.c"
        exe = tmp / "h.exe"
        src.write_text(HARNESS, encoding="ascii")
        (tmp / "n32l40x.h").write_text(
            "#ifndef N32L40X_H\n#define N32L40X_H\n"
            "#define GPIOA ((void*)0)\n#define GPIO_PIN_12 12U\n"
            "#define Bit_RESET 0\n"
            "int GPIO_ReadInputDataBit(void*,unsigned);\n"
            "void NVIC_SystemReset(void);\n#endif\n",
            encoding="ascii",
        )
        cmd = [cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
               "-I", str(tmp), "-I", str(ROOT / "include"), str(src),
               str(ROOT / "src/at_config.c"), str(ROOT / "src/f39_command.c"),
               str(ROOT / "src/plate_encoding.c"), str(ROOT / "src/f39_config_adapter.c"), str(ROOT / "src/f39_reply.c"),
               str(ROOT / "src/sms_command.c"), str(ROOT / "src/terminal_identity.c"),
               "-lm", "-o", str(exe)]
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if r.returncode:
            print(r.stdout + r.stderr, end="")
            return r.returncode
        r = subprocess.run([str(exe)], cwd=ROOT, capture_output=True, text=True)
        if r.returncode:
            print(r.stdout + r.stderr, end="")
            return r.returncode
    print("test_at_config_serial_f39: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
