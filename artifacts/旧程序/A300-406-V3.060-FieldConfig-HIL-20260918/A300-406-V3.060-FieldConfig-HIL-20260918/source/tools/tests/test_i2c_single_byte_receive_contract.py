from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DRIVER = (ROOT / "src/i2c_accel.c").read_text(encoding="utf-8")


def function_body(name: str) -> str:
    start = DRIVER.index(name)
    brace = DRIVER.index("{", start)
    depth = 0
    for pos in range(brace, len(DRIVER)):
        if DRIVER[pos] == "{":
            depth += 1
        elif DRIVER[pos] == "}":
            depth -= 1
            if depth == 0:
                return DRIVER[brace : pos + 1]
    raise AssertionError(f"unterminated function: {name}")


body = function_body("static da218e_fail_stage_t da218e_read_id")

# N32/STM32 single-byte master receive contract: wait for ADDR without
# clearing it, disable ACK, explicitly clear ADDR, issue STOP, then wait for
# RXNE and read the only byte.  I2C_CheckEvent(RXMODE) is forbidden here
# because it reads STS1/STS2 and clears ADDR too early.
addr_send = body.index("I2C_DIRECTION_RECV")
addr_wait = body.index("i2c_wait_flag(I2C_FLAG_ADDRF", addr_send)
ack_off = body.index("I2C_ConfigAck(BSP_I2C, DISABLE)", addr_wait)
clear_sts1 = body.index("(void)BSP_I2C->STS1", ack_off)
clear_sts2 = body.index("(void)BSP_I2C->STS2", clear_sts1)
stop = body.index("I2C_GenerateStop(BSP_I2C, ENABLE)", clear_sts2)
rxne = body.index("i2c_wait_flag(I2C_FLAG_RXDATNE", stop)
recv = body.index("I2C_RecvData(BSP_I2C)", rxne)
ack_on = body.index("I2C_ConfigAck(BSP_I2C, ENABLE)", recv)

assert addr_send < addr_wait < ack_off < clear_sts1 < clear_sts2 < stop < rxne < recv < ack_on
assert "I2C_EVT_MASTER_RXMODE_FLAG" not in body

print("I2C single-byte receive ordering contract: PASS")
