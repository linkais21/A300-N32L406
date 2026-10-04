#!/usr/bin/env python3
"""Contract: an unresponsive EC800M in READY must be recovered, not retried forever.

Field capture ReceivedTofile-COM4-2026_9_6_18-31-36.txt: at 07:00 local the
module stopped answering AT+QISEND. Every subsequent send failed at the prompt
stage -- 1871 of them -- with zero received bytes and no recovery for the rest
of the log, because EC800M_STATE_READY was the one state with no timeout of its
own. The device stayed "online" from its own point of view while sending
nothing.

These are source contracts rather than a compiled harness: the recovery lives
in the modem state machine, which needs the whole DMA/UART/SDK environment to
link. What must not silently regress is the wiring itself.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "src" / "ec800m.c").read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def function_body(name: str) -> str:
    match = re.search(rf"\b{name}\s*\([^;]*?\)\s*\{{", SOURCE, re.S)
    require(match is not None, f"missing function body: {name}")
    start = match.end() - 1
    depth = 0
    for index in range(start, len(SOURCE)):
        if SOURCE[index] == "{":
            depth += 1
        elif SOURCE[index] == "}":
            depth -= 1
            if depth == 0:
                return SOURCE[start + 1:index]
    raise AssertionError(f"unterminated function body: {name}")


def main() -> None:
    require("EC800M_SEND_FAIL_RESET_STREAK" in SOURCE,
            "no consecutive-send-failure threshold is defined")

    threshold = re.search(
        r"#define\s+EC800M_SEND_FAIL_RESET_STREAK\s+(\d+)U?", SOURCE)
    require(threshold is not None, "send-failure threshold is not a plain constant")
    count = int(threshold.group(1))
    require(1 < count <= 32,
            f"send-failure threshold {count} is outside a sane 2..32 range")

    send = function_body("ec800m_tcp_send")
    # A prompt-stage failure is the unresponsive-module signature: the module
    # did not even answer the command, unlike a payload or result failure.
    require(re.search(r"at_wait_prompt_owned[\s\S]{0,300}?\+\+s_send_fail_streak",
                      send) is not None,
            "a prompt-stage failure does not advance the recovery counter")
    require(re.search(r"SEND OK[\s\S]{0,200}?s_send_fail_streak\s*=\s*0U",
                      send) is not None,
            "a successful send does not clear the recovery counter")

    machine = SOURCE[SOURCE.index("case EC800M_STATE_READY:"):]
    machine = machine[:machine.index("case EC800M_STATE_ERROR:")]
    require("s_send_fail_streak >= EC800M_SEND_FAIL_RESET_STREAK" in machine,
            "READY does not act on the send-failure streak")
    require("ec800m_reset()" in machine,
            "READY does not recover the module when the streak is reached")

    # The reset must re-arm the counter, or the module would be power-cycled
    # again immediately on the next failure.
    reset = function_body("ec800m_reset")
    require("s_send_fail_streak = 0U" in reset,
            "ec800m_reset() does not clear the recovery counter")
    init = function_body("ec800m_init")
    require("s_send_fail_streak = 0U" in init,
            "ec800m_init() does not clear the recovery counter")

    # The recovery must not be driven by elapsed time: TICK_MS() is frozen
    # while STOP1 suspends the tick timer, and this failure happens during
    # sleep, so a time-based watchdog would effectively never fire.
    require(not re.search(r"s_send_fail_streak[\s\S]{0,120}?TICK_MS", machine),
            "the recovery trigger must not depend on TICK_MS")

    print("test_ec800m_send_recovery: PASS")


if __name__ == "__main__":
    main()