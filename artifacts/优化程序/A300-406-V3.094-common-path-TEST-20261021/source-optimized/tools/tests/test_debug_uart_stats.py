"""Exercise actual UART output counters and bounded timeout without hardware."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def test_uart_stats():
    with tempfile.TemporaryDirectory(prefix="debug_uart_stats_") as td:
        p = Path(td)
        (p / "config.h").write_text('#define DBG_UART 1\n', encoding="ascii")
        (p / "n32l40x.h").write_text(
            '#include <stdint.h>\n#define USART_FLAG_TXDE 1\n#define RESET 0\n'
            'int USART_GetFlagStatus(int,int);\nvoid USART_SendData(int,uint8_t);\n', encoding="ascii")
        (p / "test.c").write_text(r'''
#include <assert.h>
#include "debug_uart.h"
static unsigned polls, waits, sends;
int USART_GetFlagStatus(int uart,int flag) {
    assert(uart==1 && flag==1);return polls++ >= waits;
}
void USART_SendData(int uart,uint8_t c) { assert(uart==1 && c=='X');sends++; }
int main(void) {
    dbg_uart_stats_reset();dbg_putchar('X');
    assert(sends==1 && dbg_uart_bytes_sent()==1 && dbg_uart_wait_cycles()==0);
    polls=0;waits=3;dbg_putchar('X');
    assert(sends==2 && dbg_uart_bytes_sent()==2 && dbg_uart_wait_cycles()==3);
    polls=0;waits=100001;dbg_putchar('X');
    assert(polls==100000 && sends==2 && dbg_uart_bytes_sent()==2);
    assert(dbg_uart_wait_cycles()==100003);
    dbg_uart_stats_reset();assert(!dbg_uart_wait_cycles() && !dbg_uart_bytes_sent());
    polls=waits=0;dbg_putchar('X');assert(sends==3 && dbg_uart_bytes_sent()==1);
    return 0;
}
''', encoding="ascii")
        cc = shutil.which("gcc") or shutil.which("clang")
        assert cc
        command = [cc, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(p),
                   "-I", str(ROOT / "include"), str(p / "test.c"),
                   str(ROOT / "src/debug_uart.c"), "-o", str(p / "test.exe")]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        result = subprocess.run([str(p / "test.exe")], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr


if __name__ == "__main__":
    test_uart_stats()
    print("debug UART stats: PASS (ready, wait, timeout, reset, recovery)")
