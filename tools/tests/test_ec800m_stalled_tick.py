"""Production modem waits must terminate even if the timer interrupt stops."""
import shutil
import subprocess
import tempfile
from pathlib import Path

from test_ec800m_dma_wrap import HEADERS, PREFIX

ROOT = Path(__file__).resolve().parents[2]
HARNESS = PREFIX.replace(
    "void IWDG_ReloadKey(void) { ++g_tick_ms; }",
    "static unsigned feeds; static bool frozen=true;\n"
    "void IWDG_ReloadKey(void) { ++feeds; if(!frozen)++g_tick_ms; }")
HARNESS = HARNESS.replace(
    "{ (void)u; (void)flag; return SET; }",
    "{ (void)u; return flag==USART_FLAG_RXDNE ? host_rx_stuck : SET; }")
HARNESS = "static int host_rx_stuck;\n" + HARNESS + r'''
#include <string.h>
#include "ec800m.c"
static void host_tx(uint8_t data){(void)data;}
int main(int argc,char **argv){
    assert(argc==2);host_remaining=1024U;
    if(!strcmp(argv[1],"response")){
        assert(!at_send_wait("AT","OK",10));
    }else if(!strcmp(argv[1],"prompt")){
        assert(at_owner_acquire(AT_OWNER_BLOCKING));
        assert(!at_wait_prompt_owned("AT",10));at_owner_release(AT_OWNER_BLOCKING);
    }else if(!strcmp(argv[1],"drain")){
        EC800M_RX_BUF[0]='\r';host_remaining=1023U;
        assert(qird_drain_before_command()==1U);
    }else if(!strcmp(argv[1],"flush")){
        assert(qird_flush_after_failure(25U,400U)==0U);
    }else if(!strcmp(argv[1],"qird")){
        const uint8_t *p=NULL;uint16_t n=0;ec800m_qird_diag_t d={0};
        assert(!qird_collect_payload(0U,10U,&p,&n,&d,10U));
        assert(!p && !n);
    }else if(!strcmp(argv[1],"alive")){
        assert(!ec800m_is_alive(10U));
    }else if(!strcmp(argv[1],"rx_stuck")){
        host_rx_stuck=SET;assert(!ec800m_is_alive(10U));
    }else assert(0);
    assert(g_tick_ms==0 && feeds>0 && s_at_owner==AT_OWNER_NONE);
    /* Recovery releases the owner: a later healthy clock/response works. */
    frozen=false;host_rx_stuck=RESET;s_rx_rd=0U;host_remaining=1020U;
    memcpy(EC800M_RX_BUF,"OK\r\n",4);
    assert(at_send_wait("","OK",10U));assert(s_at_owner==AT_OWNER_NONE);
    puts("PASS");return 0;
}
'''


def main():
    cc = shutil.which("gcc") or shutil.which("clang")
    assert cc, "host compiler required"
    failures = []
    with tempfile.TemporaryDirectory(prefix="ec800m_stalled_tick_") as td:
        p = Path(td)
        for name, text in HEADERS.items():
            (p / name).write_text(text, encoding="ascii")
        (p / "h.c").write_text(HARNESS, encoding="ascii")
        exe = p / "test.exe"
        subprocess.run([cc, "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror",
                        "-Wno-dangling-else", "-ffunction-sections", "-fdata-sections",
                        "-I", str(p), "-I", str(ROOT / "include"), "-I", str(ROOT / "src"),
                        str(p / "h.c"), str(ROOT / "src/ec800m_at_response.c"),
                        "-Wl,--gc-sections", "-o", str(exe)], check=True, timeout=60)
        for case in ("response", "prompt", "drain", "flush", "qird", "alive", "rx_stuck"):
            try:
                run = subprocess.run([str(exe), case], capture_output=True, text=True, timeout=3)
                if run.returncode:
                    failures.append(f"{case}: {run.stderr}")
                else:
                    print(f"{case}: PASS")
            except subprocess.TimeoutExpired:
                failures.append(f"{case}: TIMEOUT (frozen tick keeps watchdog-fed wait alive)")
        assert not failures, "\n".join(failures)


if __name__ == "__main__":
    main()
