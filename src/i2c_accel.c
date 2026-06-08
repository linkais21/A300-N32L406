#include "i2c_accel.h"
#include "config.h"
#include "hw_init.h"
#include "debug_uart.h"
#include "n32l40x.h"
#include <stdlib.h>

/* DA218E register map (datasheet Table 14) */
#define DA218E_REG_CHIPID      0x01
#define DA218E_REG_ACC_X_LSB   0x02
#define DA218E_REG_ACC_X_MSB   0x03
#define DA218E_REG_ACC_Y_LSB   0x04
#define DA218E_REG_ACC_Y_MSB   0x05
#define DA218E_REG_ACC_Z_LSB   0x06
#define DA218E_REG_ACC_Z_MSB   0x07
#define DA218E_REG_RANGE       0x0F
#define DA218E_REG_ODR_AXIS    0x10
#define DA218E_REG_MODE_BW     0x11
#define DA218E_REG_INT_EN      0x16

/* RANGE register fs[1:0]: 00=±2g 01=±4g 10=±8g (Table 31) */
#define DA218E_RANGE_2G   0x00
/* ODR_AXIS ODR[3:0]: 0111=125Hz (Table 33) */
#define DA218E_ODR_125HZ  0x07
/* MODE_BW: PWR_OFF=0 (normal), BW=00 (1/2 ODR), autosleep=0 (Table 35) */
#define DA218E_MODE_NORMAL 0x00

static uint8_t s_addr = DA218E_I2C_ADDR;
static int16_t s_vib_threshold = 100;   /* raw units ≈ ±2g/4096 * threshold */

/* ── I2C helpers ──────────────────────────────────────────────────────────── */
static bool i2c_wait_event(uint32_t event, uint32_t timeout_ms)
{
    uint32_t t = TICK_MS();
    while (!I2C_CheckEvent(BSP_I2C, event)) {
        if (TICK_MS() - t > timeout_ms) return false;
    }
    return true;
}

static bool i2c_write_reg(uint8_t reg, uint8_t val)
{
    I2C_GenerateStart(BSP_I2C, ENABLE);
    if (!i2c_wait_event(I2C_EVT_MASTER_MODE_FLAG, 5)) goto fail;

    I2C_SendAddr7bit(BSP_I2C, s_addr, I2C_DIRECTION_SEND);
    if (!i2c_wait_event(I2C_EVT_MASTER_TXMODE_FLAG, 5)) goto fail;

    I2C_SendData(BSP_I2C, reg);
    if (!i2c_wait_event(I2C_EVT_MASTER_DATA_SENDING, 5)) goto fail;

    I2C_SendData(BSP_I2C, val);
    if (!i2c_wait_event(I2C_EVT_MASTER_DATA_SENDED, 5)) goto fail;

    I2C_GenerateStop(BSP_I2C, ENABLE);
    return true;
fail:
    I2C_GenerateStop(BSP_I2C, ENABLE);
    return false;
}

static bool i2c_read_regs(uint8_t reg, uint8_t *buf, uint8_t len)
{
    I2C_GenerateStart(BSP_I2C, ENABLE);
    if (!i2c_wait_event(I2C_EVT_MASTER_MODE_FLAG, 5)) goto fail;

    I2C_SendAddr7bit(BSP_I2C, s_addr, I2C_DIRECTION_SEND);
    if (!i2c_wait_event(I2C_EVT_MASTER_TXMODE_FLAG, 5)) goto fail;

    I2C_SendData(BSP_I2C, reg);
    if (!i2c_wait_event(I2C_EVT_MASTER_DATA_SENDED, 5)) goto fail;

    I2C_GenerateStart(BSP_I2C, ENABLE);
    if (!i2c_wait_event(I2C_EVT_MASTER_MODE_FLAG, 5)) goto fail;

    I2C_SendAddr7bit(BSP_I2C, s_addr, I2C_DIRECTION_RECV);
    if (!i2c_wait_event(I2C_EVT_MASTER_RXMODE_FLAG, 5)) goto fail;

    if (len == 1) I2C_ConfigAck(BSP_I2C, DISABLE);

    for (uint8_t i = 0; i < len; i++) {
        if (i == len - 2) I2C_ConfigAck(BSP_I2C, DISABLE);
        if (!i2c_wait_event(I2C_EVT_MASTER_DATA_RECVD_FLAG, 5)) goto fail;
        buf[i] = I2C_RecvData(BSP_I2C);
    }
    I2C_GenerateStop(BSP_I2C, ENABLE);
    I2C_ConfigAck(BSP_I2C, ENABLE);
    return true;
fail:
    I2C_GenerateStop(BSP_I2C, ENABLE);
    I2C_ConfigAck(BSP_I2C, ENABLE);
    return false;
}

/* ── Public ───────────────────────────────────────────────────────────────── */
void i2c_accel_init(void)
{
    delay_ms(50);

    /* Step-by-step I2C diagnostic */
    I2C_GenerateStart(BSP_I2C, ENABLE);
    if (!i2c_wait_event(I2C_EVT_MASTER_MODE_FLAG, 5)) {
        dbg_printf("[ACCEL] fail: START\r\n"); goto done; }

    I2C_SendAddr7bit(BSP_I2C, s_addr, I2C_DIRECTION_SEND);
    if (!i2c_wait_event(I2C_EVT_MASTER_TXMODE_FLAG, 5)) {
        dbg_printf("[ACCEL] fail: ADDR 0x%02x (no ACK?)\r\n", s_addr);
        I2C_GenerateStop(BSP_I2C, ENABLE); goto done; }

    I2C_SendData(BSP_I2C, DA218E_REG_CHIPID);
    if (!i2c_wait_event(I2C_EVT_MASTER_DATA_SENDED, 5)) {
        dbg_printf("[ACCEL] fail: REG send\r\n");
        I2C_GenerateStop(BSP_I2C, ENABLE); goto done; }

    I2C_GenerateStart(BSP_I2C, ENABLE);
    if (!i2c_wait_event(I2C_EVT_MASTER_MODE_FLAG, 5)) {
        dbg_printf("[ACCEL] fail: RESTART\r\n");
        I2C_GenerateStop(BSP_I2C, ENABLE); goto done; }

    I2C_SendAddr7bit(BSP_I2C, s_addr, I2C_DIRECTION_RECV);
    if (!i2c_wait_event(I2C_EVT_MASTER_RXMODE_FLAG, 5)) {
        dbg_printf("[ACCEL] fail: ADDR RD\r\n");
        I2C_GenerateStop(BSP_I2C, ENABLE); goto done; }

    I2C_ConfigAck(BSP_I2C, DISABLE);
    if (!i2c_wait_event(I2C_EVT_MASTER_DATA_RECVD_FLAG, 5)) {
        dbg_printf("[ACCEL] fail: DATA recv\r\n");
        I2C_GenerateStop(BSP_I2C, ENABLE); I2C_ConfigAck(BSP_I2C, ENABLE); goto done; }

    {
        uint8_t id = I2C_RecvData(BSP_I2C);
        I2C_GenerateStop(BSP_I2C, ENABLE);
        I2C_ConfigAck(BSP_I2C, ENABLE);
        dbg_printf("[ACCEL] addr=0x%02x ID=0x%02x%s\r\n",
                   s_addr, id, id == 0x13 ? " OK" : " WRONG(exp 0x13)");
        if (id != 0x13) goto done;
        i2c_write_reg(DA218E_REG_RANGE,    DA218E_RANGE_2G);
        i2c_write_reg(DA218E_REG_ODR_AXIS, DA218E_ODR_125HZ);
        i2c_write_reg(DA218E_REG_MODE_BW,  DA218E_MODE_NORMAL);
        return;
    }
done:
    dbg_printf("[ACCEL] not found\r\n");
    /* Configure range and ODR first, then exit suspend mode last */
    i2c_write_reg(DA218E_REG_RANGE,    DA218E_RANGE_2G);
    i2c_write_reg(DA218E_REG_ODR_AXIS, DA218E_ODR_125HZ);
    i2c_write_reg(DA218E_REG_MODE_BW,  DA218E_MODE_NORMAL);  /* clears PWR_OFF=1 default */
}

bool i2c_accel_read(accel_data_t *out)
{
    uint8_t buf[6];
    if (!i2c_read_regs(DA218E_REG_ACC_X_LSB, buf, 6)) return false;
    out->x = (int16_t)((buf[1] << 8) | buf[0]) >> 4;
    out->y = (int16_t)((buf[3] << 8) | buf[2]) >> 4;
    out->z = (int16_t)((buf[5] << 8) | buf[4]) >> 4;
    return true;
}

bool i2c_accel_detect_vibration(void)
{
    accel_data_t d;
    if (!i2c_accel_read(&d)) return false;
    int16_t mag = abs(d.x) + abs(d.y) + abs(d.z);
    return mag > s_vib_threshold;
}
