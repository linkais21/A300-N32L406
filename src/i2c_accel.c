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
#define DA218E_REG_INT_SET1    0x16
#define DA218E_REG_INT_MAP1    0x19
#define DA218E_REG_INT_CONFIG  0x20
#define DA218E_REG_INT_LATCH   0x21
#define DA218E_REG_ACTIVE_DUR  0x27
#define DA218E_REG_ACTIVE_THS  0x28

/* RANGE register fs[1:0]: 00=±2g 01=±4g 10=±8g (Table 31) */
#define DA218E_RANGE_2G   0x00
/* ODR_AXIS ODR[3:0]: 0111=125Hz (Table 33) */
#define DA218E_ODR_125HZ  0x07
/* MODE_BW: PWR_OFF=0 (normal), BW=00 (1/2 ODR), autosleep=0 (Table 35) */
#define DA218E_MODE_NORMAL 0x00

static uint8_t s_addr = DA218E_I2C_ADDR;
static accel_diag_t s_diag;
static uint32_t s_last_vibration_log_ms;
#define DA218E_INIT_MAX_RETRIES 3U
#define DA218E_BUS_RECOVERY_CLOCKS 9U

static uint8_t bus_scl(void)
{
    return (uint8_t)GPIO_ReadInputDataBit(BSP_I2C_SCL_PORT, BSP_I2C_SCL_PIN);
}

static uint8_t bus_sda(void)
{
    return (uint8_t)GPIO_ReadInputDataBit(BSP_I2C_SDA_PORT, BSP_I2C_SDA_PIN);
}

static void da218e_bus_recover(void)
{
    GPIO_InitType g;
    uint8_t pulses;

    I2C_Enable(BSP_I2C, DISABLE);
    GPIO_SetBits(BSP_I2C_SCL_PORT, BSP_I2C_SCL_PIN);
    GPIO_SetBits(BSP_I2C_SDA_PORT, BSP_I2C_SDA_PIN);
    GPIO_InitStruct(&g);
    g.Pin = BSP_I2C_SCL_PIN | BSP_I2C_SDA_PIN;
    g.GPIO_Mode = GPIO_Mode_Out_OD;
    g.GPIO_Slew_Rate = GPIO_Slew_Rate_High;
    g.GPIO_Current = GPIO_DC_4mA;
    g.GPIO_Pull = GPIO_Pull_Up;
    GPIO_InitPeripheral(GPIOD, &g);
    delay_us(10U);
    dbg_printf("[ACCEL] recovery released SCL=%u SDA=%u\r\n", bus_scl(), bus_sda());

    for (pulses = 0U; pulses < DA218E_BUS_RECOVERY_CLOCKS; ++pulses) {
        if (bus_sda() != 0U) break;
        GPIO_ResetBits(BSP_I2C_SCL_PORT, BSP_I2C_SCL_PIN);
        delay_us(5U);
        GPIO_SetBits(BSP_I2C_SCL_PORT, BSP_I2C_SCL_PIN);
        delay_us(5U);
        if (bus_scl() == 0U) break;
    }

    /* Generate a STOP while SCL is released high, then restore AF/I2C. */
    GPIO_ResetBits(BSP_I2C_SDA_PORT, BSP_I2C_SDA_PIN);
    delay_us(5U);
    GPIO_SetBits(BSP_I2C_SCL_PORT, BSP_I2C_SCL_PIN);
    delay_us(5U);
    GPIO_SetBits(BSP_I2C_SDA_PORT, BSP_I2C_SDA_PIN);
    delay_us(5U);
    dbg_printf("[ACCEL] recovery pulses=%u SCL=%u SDA=%u\r\n",
               pulses, bus_scl(), bus_sda());
    hw_i2c_init();
    dbg_printf("[ACCEL] bus post SCL=%u SDA=%u STS1=%04x STS2=%04x\r\n",
               bus_scl(), bus_sda(), BSP_I2C->STS1, BSP_I2C->STS2);
}

/* EMA基线 + delta阈值方案（与震动唤醒判断统一）
 * EMA_SHIFT=5 → α=1/32，基线缓慢跟踪重力方向变化，去除直流偏置
 * VIB_THRESH：三轴|delta|之和超过此值即单次命中（静止≤89，晃动≥135，250留余量）
 * VIB_CONFIRM：连续命中次数达到才确认"在运动"（×200ms=持续时间）
 * 中间一次未命中即清零——防单次尖峰误判 */
#define VIB_EMA_SHIFT  5     /* EMA α = 1/32 */
#define VIB_THRESH     150   /* LSB，三轴delta之和阈值，不准时只需改此值 */
#define VIB_CONFIRM    15    /* 连续15次×200ms = 3s确认，太敏感改25，唤不醒改10 */

/* Work-mode product sensitivity levels are not DA218E register values. */
#define VIBRATION_SAMPLE_INTERVAL_MS 200U
#define VIBRATION_CONFIRM_GAP_MS 1000U
#define VIBRATION_SENSITIVITY_LEVEL_10 10U
#define VIBRATION_SENSITIVITY_LEVEL_COUNT 10U

static int32_t s_ema_x = 0, s_ema_y = 0, s_ema_z = 0;  /* EMA × (1<<VIB_EMA_SHIFT) */
static uint8_t s_ema_init = 0;
static uint8_t s_vib_count = 0;
static bool    s_is_moving = false;
static int32_t s_window_ema_x = 0, s_window_ema_y = 0, s_window_ema_z = 0;
static uint8_t s_window_ema_init = 0;
static uint32_t s_last_vibration_sample_ms = 0U;
static bool s_vibration_sample_seen = false;
static uint32_t s_vibration_episode_start_ms;
static uint32_t s_vibration_last_hit_ms;
static uint16_t s_vibration_episode_hits;

static uint16_t vibration_threshold_by_level(uint8_t sensitivity_level)
{
    static const uint16_t thresholds[VIBRATION_SENSITIVITY_LEVEL_COUNT] = {
        330U, 310U, 290U, 270U, 250U, 230U, 210U, 190U, 170U, 150U
    };

    if (sensitivity_level == 0U ||
        sensitivity_level > VIBRATION_SENSITIVITY_LEVEL_COUNT) {
        sensitivity_level = VIBRATION_SENSITIVITY_LEVEL_10;
    }
    return thresholds[sensitivity_level - 1U];
}

typedef enum {
    DA218E_FAIL_NONE = 0,
    DA218E_FAIL_BUS,
    DA218E_FAIL_START,
    DA218E_FAIL_ADDR_W,
    DA218E_FAIL_REG,
    DA218E_FAIL_RESTART,
    DA218E_FAIL_ADDR_R,
    DA218E_FAIL_DATA,
} da218e_fail_stage_t;

static const char *da218e_fail_name(da218e_fail_stage_t stage)
{
    static const char *const names[] = {
        "NONE", "BUS", "START", "ADDR-W", "REG", "RESTART", "ADDR-R", "DATA"
    };
    return stage <= DA218E_FAIL_DATA ? names[stage] : "UNKNOWN";
}

/* ── I2C helpers ──────────────────────────────────────────────────────────── */
static bool i2c_wait_event(uint32_t event, uint32_t timeout_ms)
{
    uint32_t t = TICK_MS();
    while (!I2C_CheckEvent(BSP_I2C, event)) {
        if (TICK_MS() - t > timeout_ms) return false;
    }
    return true;
}

static bool i2c_wait_flag(uint32_t flag, uint32_t timeout_ms)
{
    uint32_t t = TICK_MS();
    while (I2C_GetFlag(BSP_I2C, flag) == RESET) {
        if (TICK_MS() - t > timeout_ms) return false;
    }
    return true;
}

static bool i2c_write_reg(uint8_t reg, uint8_t val)
{
    I2C_GenerateStart(BSP_I2C, ENABLE);
    if (!i2c_wait_event(I2C_EVT_MASTER_MODE_FLAG, 5)) goto fail;

    I2C_SendAddr7bit(BSP_I2C, (uint8_t)(s_addr << 1), I2C_DIRECTION_SEND);
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
    if (buf == NULL || len == 0U) return false;
    I2C_GenerateStart(BSP_I2C, ENABLE);
    if (!i2c_wait_event(I2C_EVT_MASTER_MODE_FLAG, 5)) goto fail;

    I2C_SendAddr7bit(BSP_I2C, (uint8_t)(s_addr << 1), I2C_DIRECTION_SEND);
    if (!i2c_wait_event(I2C_EVT_MASTER_TXMODE_FLAG, 5)) goto fail;

    I2C_SendData(BSP_I2C, reg);
    if (!i2c_wait_event(I2C_EVT_MASTER_DATA_SENDED, 5)) goto fail;

    I2C_GenerateStart(BSP_I2C, ENABLE);
    if (!i2c_wait_event(I2C_EVT_MASTER_MODE_FLAG, 5)) goto fail;

    I2C_SendAddr7bit(BSP_I2C, (uint8_t)(s_addr << 1), I2C_DIRECTION_RECV);
    if (!i2c_wait_flag(I2C_FLAG_ADDRF, 5)) goto fail;

    if (len == 1U) {
        I2C_ConfigAck(BSP_I2C, DISABLE);
        (void)BSP_I2C->STS1;
        (void)BSP_I2C->STS2;
        I2C_GenerateStop(BSP_I2C, ENABLE);
        if (!i2c_wait_flag(I2C_FLAG_RXDATNE, 5)) goto fail;
        buf[0] = I2C_RecvData(BSP_I2C);
    } else if (len == 2U) {
        BSP_I2C->CTRL1 |= 0x0800U; /* ACKPOS: NACK the next received byte. */
        (void)BSP_I2C->STS1;
        (void)BSP_I2C->STS2;
        I2C_ConfigAck(BSP_I2C, DISABLE);
        if (!i2c_wait_flag(I2C_FLAG_BYTEF, 5)) goto fail;
        I2C_GenerateStop(BSP_I2C, ENABLE);
        buf[0] = I2C_RecvData(BSP_I2C);
        buf[1] = I2C_RecvData(BSP_I2C);
    } else {
        uint8_t pos = 0U;
        I2C_ConfigAck(BSP_I2C, ENABLE);
        (void)BSP_I2C->STS1;
        (void)BSP_I2C->STS2;
        while (len > 3U) {
            if (!i2c_wait_flag(I2C_FLAG_RXDATNE, 5)) goto fail;
            buf[pos++] = I2C_RecvData(BSP_I2C);
            --len;
        }
        if (!i2c_wait_flag(I2C_FLAG_BYTEF, 5)) goto fail;
        I2C_ConfigAck(BSP_I2C, DISABLE);
        buf[pos++] = I2C_RecvData(BSP_I2C);
        if (!i2c_wait_flag(I2C_FLAG_BYTEF, 5)) goto fail;
        I2C_GenerateStop(BSP_I2C, ENABLE);
        buf[pos++] = I2C_RecvData(BSP_I2C);
        buf[pos] = I2C_RecvData(BSP_I2C);
    }
    BSP_I2C->CTRL1 &= ~0x0800U;
    I2C_ConfigAck(BSP_I2C, ENABLE);
    return true;
fail:
    I2C_GenerateStop(BSP_I2C, ENABLE);
    BSP_I2C->CTRL1 &= ~0x0800U;
    I2C_ConfigAck(BSP_I2C, ENABLE);
    return false;
}

static da218e_fail_stage_t da218e_read_id(uint8_t addr, uint8_t *id)
{
    s_addr = addr;
    if (GPIO_ReadInputDataBit(BSP_I2C_SCL_PORT, BSP_I2C_SCL_PIN) == 0 ||
        GPIO_ReadInputDataBit(BSP_I2C_SDA_PORT, BSP_I2C_SDA_PIN) == 0)
        return DA218E_FAIL_BUS;
    I2C_EnableSoftwareReset(BSP_I2C, ENABLE);
    I2C_EnableSoftwareReset(BSP_I2C, DISABLE);
    /* SWRESET clears the peripheral configuration, including PE. */
    hw_i2c_init();
    I2C_GenerateStart(BSP_I2C, ENABLE);
    if (!i2c_wait_event(I2C_EVT_MASTER_MODE_FLAG, 5)) return DA218E_FAIL_START;
    I2C_SendAddr7bit(BSP_I2C, (uint8_t)(addr << 1), I2C_DIRECTION_SEND);
    if (!i2c_wait_event(I2C_EVT_MASTER_TXMODE_FLAG, 5)) { I2C_GenerateStop(BSP_I2C, ENABLE); return DA218E_FAIL_ADDR_W; }
    I2C_SendData(BSP_I2C, DA218E_REG_CHIPID);
    if (!i2c_wait_event(I2C_EVT_MASTER_DATA_SENDED, 5)) { I2C_GenerateStop(BSP_I2C, ENABLE); return DA218E_FAIL_REG; }
    I2C_GenerateStart(BSP_I2C, ENABLE);
    if (!i2c_wait_event(I2C_EVT_MASTER_MODE_FLAG, 5)) { I2C_GenerateStop(BSP_I2C, ENABLE); return DA218E_FAIL_RESTART; }
    I2C_SendAddr7bit(BSP_I2C, (uint8_t)(addr << 1), I2C_DIRECTION_RECV);
    if (!i2c_wait_flag(I2C_FLAG_ADDRF, 5)) { I2C_GenerateStop(BSP_I2C, ENABLE); return DA218E_FAIL_ADDR_R; }
    I2C_ConfigAck(BSP_I2C, DISABLE);
    (void)BSP_I2C->STS1;
    (void)BSP_I2C->STS2;
    I2C_GenerateStop(BSP_I2C, ENABLE);
    if (!i2c_wait_flag(I2C_FLAG_RXDATNE, 5)) { I2C_ConfigAck(BSP_I2C, ENABLE); return DA218E_FAIL_DATA; }
    *id = I2C_RecvData(BSP_I2C);
    I2C_ConfigAck(BSP_I2C, ENABLE);
    return DA218E_FAIL_NONE;
}

/* ── Public ───────────────────────────────────────────────────────────────── */
void i2c_accel_init(void)
{
    s_diag.x = 0;
    s_diag.y = 0;
    s_diag.z = 0;
    s_diag.sample_count = 0U;
    s_diag.read_fail_count = 0U;
    s_diag.delta = 0U;
    s_diag.threshold = 0U;
    s_diag.vibration_hit_count = 0U;
    s_diag.address = 0U;
    s_diag.read_ok = false;
    s_diag.vibration_hit = false;
    s_last_vibration_log_ms = 0U;
    delay_ms(50);
    dbg_printf("[ACCEL] bus af SCL=%u SDA=%u STS1=%04x STS2=%04x\r\n",
               bus_scl(), bus_sda(), BSP_I2C->STS1, BSP_I2C->STS2);
    if (bus_scl() == 0U || bus_sda() == 0U)
        da218e_bus_recover();
    for (uint8_t attempt = 0; attempt < DA218E_INIT_MAX_RETRIES; attempt++) {
        uint8_t id = 0;
        uint8_t addrs[4] = { DA218E_I2C_ADDR, DA218E_I2C_FALLBACK_ADDR,
                             DA218E_I2C_LEGACY_ADDR, DA218E_I2C_LEGACY_FALLBACK_ADDR };
        for (uint8_t i = 0; i < 4; i++) {
            da218e_fail_stage_t stage;
            dbg_printf("[ACCEL] probe addr=0x%02x try=%u\r\n", addrs[i], attempt + 1U);
            stage = da218e_read_id(addrs[i], &id);
            if (stage != DA218E_FAIL_NONE) {
                dbg_printf("[ACCEL] fail addr=0x%02x stage=%s\r\n",
                           addrs[i], da218e_fail_name(stage));
                continue;
            }
            dbg_printf("[ACCEL] addr=0x%02x ID=0x%02x%s\r\n", s_addr, id,
                       id == 0x13 ? " OK" : " WRONG(exp 0x13)");
            if (id != 0x13) continue;
            s_diag.address = s_addr;
            (void)i2c_write_reg(DA218E_REG_RANGE, DA218E_RANGE_2G);
            (void)i2c_write_reg(DA218E_REG_ODR_AXIS, DA218E_ODR_125HZ);
            (void)i2c_write_reg(DA218E_REG_MODE_BW, DA218E_MODE_NORMAL);
            /* Active-motion interrupt is the STOP wake source.  Software
             * still confirms six seconds of samples after the wake. */
            (void)i2c_write_reg(DA218E_REG_INT_CONFIG, 0x81U);
            (void)i2c_write_reg(DA218E_REG_INT_CONFIG, 0x01U);
            (void)i2c_write_reg(DA218E_REG_INT_SET1, 0x83U);
            (void)i2c_write_reg(DA218E_REG_INT_MAP1, 0x04U);
            (void)i2c_write_reg(DA218E_REG_INT_LATCH, 0x00U);
            (void)i2c_write_reg(DA218E_REG_ACTIVE_DUR, 0x00U);
            (void)i2c_write_reg(DA218E_REG_ACTIVE_THS, 0x26U);
            return;
        }
        delay_ms(2);
    }
    dbg_printf("[ACCEL] not found after %u tries\r\n", DA218E_INIT_MAX_RETRIES);
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
    if (!i2c_accel_read(&d)) return s_is_moving;  /* I2C失败保持上次状态 */

    /* 首次采样直接初始化基线，不做判断 */
    if (!s_ema_init) {
        s_ema_x = (int32_t)d.x << VIB_EMA_SHIFT;
        s_ema_y = (int32_t)d.y << VIB_EMA_SHIFT;
        s_ema_z = (int32_t)d.z << VIB_EMA_SHIFT;
        s_ema_init = 1;
        return false;
    }

    /* EMA更新：s_ema = s_ema + (sample - s_ema/32) = s_ema×(31/32) + sample */
    s_ema_x += d.x - (s_ema_x >> VIB_EMA_SHIFT);
    s_ema_y += d.y - (s_ema_y >> VIB_EMA_SHIFT);
    s_ema_z += d.z - (s_ema_z >> VIB_EMA_SHIFT);

    int16_t delta = (int16_t)(abs(d.x - (int16_t)(s_ema_x >> VIB_EMA_SHIFT))
                            + abs(d.y - (int16_t)(s_ema_y >> VIB_EMA_SHIFT))
                            + abs(d.z - (int16_t)(s_ema_z >> VIB_EMA_SHIFT)));

    if (delta > VIB_THRESH) {
        if (s_vib_count < VIB_CONFIRM) s_vib_count++;
    } else {
        s_vib_count = 0;
    }

    s_is_moving = (s_vib_count >= VIB_CONFIRM);
    return s_is_moving;
}

bool i2c_accel_is_moving(void) { return s_is_moving; }

void i2c_accel_reset_vibration_window(void)
{
    s_window_ema_x = 0;
    s_window_ema_y = 0;
    s_window_ema_z = 0;
    s_window_ema_init = 0U;
}

void i2c_accel_prepare_wake_sampling(void)
{
    /* STOP2 suspends SysTick; make the first post-wake sample immediately
     * eligible and do not carry the pre-sleep EMA into this window. */
    i2c_accel_reset_vibration_window();
    s_last_vibration_sample_ms = TICK_MS();
    s_vibration_sample_seen = false;
    s_vibration_episode_start_ms = 0U;
    s_vibration_last_hit_ms = 0U;
    s_vibration_episode_hits = 0U;
}

bool i2c_accel_vibration_hit(uint8_t sensitivity_level)
{
    accel_data_t d;
    uint32_t now_ms = TICK_MS();
    int16_t delta;

    if (s_vibration_sample_seen &&
        now_ms - s_last_vibration_sample_ms < VIBRATION_SAMPLE_INTERVAL_MS) {
        return false;
    }
    s_last_vibration_sample_ms = now_ms;
    s_vibration_sample_seen = true;

    if (!i2c_accel_read(&d)) {
        s_diag.read_ok = false;
        s_diag.vibration_hit = false;
        ++s_diag.read_fail_count;
        i2c_accel_reset_vibration_window();
        return false;
    }

    s_diag.x = d.x;
    s_diag.y = d.y;
    s_diag.z = d.z;
    s_diag.sample_count++;
    s_diag.read_ok = true;

    if (!s_window_ema_init) {
        s_window_ema_x = (int32_t)d.x << VIB_EMA_SHIFT;
        s_window_ema_y = (int32_t)d.y << VIB_EMA_SHIFT;
        s_window_ema_z = (int32_t)d.z << VIB_EMA_SHIFT;
        s_window_ema_init = 1U;
        return false;
    }

    s_window_ema_x += d.x - (s_window_ema_x >> VIB_EMA_SHIFT);
    s_window_ema_y += d.y - (s_window_ema_y >> VIB_EMA_SHIFT);
    s_window_ema_z += d.z - (s_window_ema_z >> VIB_EMA_SHIFT);
    delta = (int16_t)(abs(d.x - (int16_t)(s_window_ema_x >> VIB_EMA_SHIFT)) +
                      abs(d.y - (int16_t)(s_window_ema_y >> VIB_EMA_SHIFT)) +
                      abs(d.z - (int16_t)(s_window_ema_z >> VIB_EMA_SHIFT)));
    s_diag.threshold = vibration_threshold_by_level(sensitivity_level);
    s_diag.delta = (uint16_t)(delta < 0 ? 0 : delta);
    s_diag.vibration_hit = delta > (int16_t)s_diag.threshold;
    if (s_diag.vibration_hit) {
        if (s_vibration_episode_hits == 0U ||
            (uint32_t)(now_ms - s_vibration_last_hit_ms) >
            VIBRATION_CONFIRM_GAP_MS) {
            s_vibration_episode_start_ms = now_ms;
            s_vibration_episode_hits = 0U;
        }
        if (s_vibration_episode_hits < UINT16_MAX)
            ++s_vibration_episode_hits;
        s_vibration_last_hit_ms = now_ms;
        ++s_diag.vibration_hit_count;
        if (TICK_MS() - s_last_vibration_log_ms >= 5000U) {
            s_last_vibration_log_ms = TICK_MS();
            dbg_printf("[ACCEL] vibration X=%d Y=%d Z=%d delta=%u threshold=%u\r\n",
                       d.x, d.y, d.z, (unsigned)s_diag.delta,
                       (unsigned)s_diag.threshold);
        }
    }
    /* A hit remains true for the active episode. This bridges brief EMA
     * misses while the physical vibration continues and lets work_mode count
     * the full six-second confirmation window. */
    if (!s_diag.vibration_hit && s_vibration_episode_hits != 0U &&
        (uint32_t)(now_ms - s_vibration_last_hit_ms) <= VIBRATION_CONFIRM_GAP_MS) {
        return true;
    }
    if (!s_diag.vibration_hit && s_vibration_episode_hits != 0U &&
        (uint32_t)(now_ms - s_vibration_last_hit_ms) > VIBRATION_CONFIRM_GAP_MS) {
        /* The episode ended.  Do not let the six-second completion latch
         * turn every later quiet sample into a permanent vibration hit. */
        s_vibration_episode_start_ms = 0U;
        s_vibration_last_hit_ms = 0U;
        s_vibration_episode_hits = 0U;
        return false;
    }
    if (s_vibration_episode_hits != 0U &&
        (uint32_t)(now_ms - s_vibration_episode_start_ms) >= 6000U &&
        s_vibration_episode_hits >= 20U) {
        return true;
    }
    return s_diag.vibration_hit;
}

bool i2c_accel_vibration_sample_due(void)
{
    return !s_vibration_sample_seen ||
           (uint32_t)(TICK_MS() - s_last_vibration_sample_ms) >=
           VIBRATION_SAMPLE_INTERVAL_MS;
}

const accel_diag_t *i2c_accel_get_diag(void)
{
    return &s_diag;
}
