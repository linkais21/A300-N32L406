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
#include <string.h>
#include "at_config.h"
#include "f39_reply.h"
#include "gps.h"
#include "sms_command.h"
#include "peripherals.h"

static device_config_t config;
static unsigned saves, system_resets;
static char console[1024];
static unsigned console_len;

volatile uint32_t g_tick_ms;
device_config_t *cfg_get(void) { return &config; }
bool cfg_store_candidate(const device_config_t *c) { config = *c; saves++; return true; }
cfg_store_result_t cfg_set_pid_result(const char pid[CFG_PID_LEN])
{ memcpy(config.pid, pid, CFG_PID_LEN); return CFG_STORE_OK; }
void cfg_save(void) { }
void jt808_set_heartbeat_s(uint16_t s) { (void)s; }
void jt808_set_report_interval(uint16_t a, uint16_t b) { (void)a; (void)b; }
void jt808_set_server(const char *ip, uint16_t p, bool b) { (void)ip; (void)p; (void)b; }
void jt808_request_reregister(void) { }
void tcp_manager_reconnect(void) { }
void gnss_vendor_set_type(gnss_type_t t) { (void)t; }
void agnss_init(gnss_type_t t) { (void)t; }
void relay_set(bool on) { (void)on; }
bool relay_get(void) { return false; }
bool gps_is_valid(void) { return true; }
const gps_data_t *gps_get_data(void) { static gps_data_t g; g.valid = true; return &g; }
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

    line("PARAM#");
    assert(strstr(console, "PRO[JT808_2013]") != 0);
    assert(strstr(console, "ICCID[89860492192080502719]") != 0);

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

    /* A genuinely unknown line is still reported as unknown. */
    line("NOSUCHCOMMAND");
    assert(strstr(console, "ERR:UNKNOWN CMD") != 0);

    /* RESET over serial schedules the restart rather than resetting inside
       the parser; at_config_process() performs it once the delay elapses. */
    system_resets = 0U;
    line("RESET#");
    assert(strstr(console, "RESET=Success!") != 0);
    assert(system_resets == 0U);
    g_tick_ms += F39_RESET_DELAY_MS + 1U;
    at_config_process();
    assert(system_resets == 1U);

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
               str(ROOT / "src/f39_config_adapter.c"), str(ROOT / "src/f39_reply.c"),
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