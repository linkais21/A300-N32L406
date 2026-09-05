#ifndef I2C_ACCEL_H
#define I2C_ACCEL_H

#include <stdint.h>
#include <stdbool.h>

typedef struct { int16_t x, y, z; } accel_data_t;
typedef struct {
    int16_t x, y, z;
    uint32_t sample_count;
    uint32_t read_fail_count;
    uint16_t delta;
    uint16_t threshold;
    uint32_t vibration_hit_count;
    uint8_t address;
    bool read_ok;
    bool vibration_hit;
} accel_diag_t;

void  i2c_accel_init(void);
bool  i2c_accel_read(accel_data_t *out);
bool  i2c_accel_detect_vibration(void);  /* 采样+更新状态，每200ms由scan_alarms调用 */
bool  i2c_accel_is_moving(void);         /* 读缓存结果，任意时刻可调用 */
bool  i2c_accel_vibration_hit(uint8_t sensitivity_level);
bool  i2c_accel_vibration_sample_due(void);
void  i2c_accel_reset_vibration_window(void);
void  i2c_accel_prepare_wake_sampling(void);
const accel_diag_t *i2c_accel_get_diag(void);

#endif
