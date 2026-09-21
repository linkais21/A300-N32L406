"""Run production query/owner code across deferred modem calls and failures."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def test_lifetime():
    stubs = {
        "at_config.h": '#include <stdbool.h>\n#include <stdint.h>\nbool at_config_execute_text_command_ack(const uint8_t*,uint16_t,void (*)(bool,void*),void*);\n',
        "ec800m.h": '''#include <stdbool.h>
#include <stdint.h>
bool ec800m_is_ready(void);
void ec800m_get_imei(char *, unsigned);
int ec800m_udp_txn_start(const char *, uint16_t, const uint8_t *, uint16_t, uint8_t *, uint16_t, uint32_t);
void ec800m_udp_txn_process(void);
int ec800m_udp_txn_result(void);
int ec800m_udp_send_once(const char *, uint16_t, const uint8_t *, uint16_t);
''',
        "config.h": '''#ifndef CONFIG_H
#define CONFIG_H
#include <stdint.h>
typedef struct { int unused; } config_t;
config_t *cfg_get(void);
#define TICK_MS() 1000U
#endif
''',
        "flash_config.h": '#include "config.h"\n',
        "work_mode.h": '#include "config.h"\nvoid work_mode_config_changed(config_t *, uint32_t);\n',
        "work_mode_sleep.h": '',
    }
    harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "cfg_query.h"
#include "service_workspace.h"
#include "config.h"
static int scenario, starts, steps, confirmations, changes;
int dbg_printf(const char *f,...){(void)f;return 0;}
bool at_config_execute_text_command_ack(const uint8_t *p, uint16_t n,
                                       void (*ack)(bool,void*), void *context) {
    (void)p; (void)n; ack(true,context); return true;
}
static const uint8_t *tx;
static uint8_t *rx, expected[16];
static uint16_t rx_cap;
static uint8_t checksum(const uint8_t *p, unsigned n) {
    uint8_t c=0; while(n--) c^=*p++; return c;
}
bool ec800m_is_ready(void) { return true; }
void ec800m_get_imei(char *p, unsigned n) {
    snprintf(p,n,"%s",scenario==3 ? "invalid" : "123456789012345");
}
config_t *cfg_get(void) { static config_t cfg; return &cfg; }
void work_mode_config_changed(config_t *c,uint32_t t) { (void)c;(void)t;changes++; }
int ec800m_udp_txn_start(const char *ip,uint16_t port,const uint8_t *p,
                        uint16_t n,uint8_t *r,uint16_t cap,uint32_t timeout) {
    (void)ip;(void)port; assert(n==16 && timeout==8000);starts++;
    if(scenario==1) return -2;
    tx=p;rx=r;rx_cap=cap;memcpy(expected,p,16);steps=0;
    return 0;
}
void ec800m_udp_txn_process(void) {
    assert(memcmp(tx,expected,16)==0); /* TX must survive the caller's return. */
    assert(!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_OTA));
    steps++;
    if(steps==3) {
        memset(rx,0xa5,rx_cap); /* RX capacity must not overlap live TX. */
        assert(memcmp(tx,expected,16)==0);
        memcpy(rx,expected,16);rx[2]=0x92;rx[14]=checksum(rx,14);
        if(scenario==2) rx[14]^=1;
    }
}
int ec800m_udp_txn_result(void) { return steps<3 ? -2 : (scenario==4 ? -1 : 16); }
int ec800m_udp_send_once(const char *ip,uint16_t port,const uint8_t *p,uint16_t n) {
    (void)ip;(void)port;assert(n==16 && p[2]==0x14);
    assert(p[14]==checksum(p,14));confirmations++;return 0;
}
static void stack_churn(void) {
    volatile uint8_t scratch[2048];
    for(unsigned i=0;i<sizeof scratch;i++)scratch[i]=(uint8_t)i;
}
int main(int argc,char **argv) {
    assert(argc==2);scenario=argv[1][0]-'0';cfg_query_init();
    assert(service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_AGNSS));
    assert(cfg_query_start()==0);cfg_query_process();assert(starts==0);
    service_workspace_release(SERVICE_WORKSPACE_OWNER_AGNSS);
    cfg_query_process();
    if(scenario!=1 && scenario!=3) {
        assert(!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_OTA));
        for(unsigned i=0;i<3;i++) {
            stack_churn();cfg_query_process();
            if(i<2) {
                assert(cfg_query_is_busy());
                assert(!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_AGNSS));
                assert(cfg_query_start()==-1);
                cfg_query_init(); /* must not abandon live modem pointers */
                assert(cfg_query_is_busy());
            }
        }
    }
    if(scenario==4) {
        for(unsigned attempt=1;attempt<3;attempt++) {
            assert(cfg_query_is_busy());cfg_query_process();
            for(unsigned i=0;i<3;i++)cfg_query_process();
        }
        assert(starts==3);
    }
    assert(!cfg_query_is_busy());
    int result=99;assert(cfg_query_take_result(&result));
    assert(result==(scenario==0 ? 0 : -1));
    assert(!cfg_query_take_result(&result));
    assert(confirmations==0 && changes==0); /* no config: no success confirmation */
    assert(service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_OTA));
    service_workspace_release(SERVICE_WORKSPACE_OWNER_OTA);
    assert(cfg_query_start()==0); /* completed/failed queries are reusable */
    puts("PASS");return 0;
}
'''
    cc = shutil.which("gcc") or shutil.which("clang")
    assert cc, "host C compiler required"
    with tempfile.TemporaryDirectory(prefix="cfg_query_lifetime_") as td:
        p = Path(td)
        for name, content in stubs.items():
            (p / name).write_text(content, encoding="ascii")
        (p / "harness.c").write_text(harness, encoding="ascii")
        exe = p / "test.exe"
        result = subprocess.run([cc, "-std=c99", "-O0", "-Wall", "-Wextra", "-Werror",
                                 "-I", str(p), "-I", str(ROOT / "include"),
                                 str(p / "harness.c"), str(ROOT / "src/cfg_query.c"),
                                 str(ROOT / "src/service_workspace.c"), "-o", str(exe)],
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        failures = []
        for case in range(5):
            result = subprocess.run([str(exe), str(case)], capture_output=True, text=True, timeout=10)
            if result.returncode:
                failures.append(f"scenario {case}: {result.stderr}")
        assert not failures, "\n".join(failures)


if __name__ == "__main__":
    test_lifetime()
    print("cfg query lifetime: PASS (5 scenarios)")
