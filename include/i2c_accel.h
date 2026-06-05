#ifndef I2C_ACCEL_H
#define I2C_ACCEL_H

#include <stdint.h>
#include <stdbool.h>

typedef struct { int16_t x, y, z; } accel_data_t;

void  i2c_accel_init(void);
bool  i2c_accel_read(accel_data_t *out);
bool  i2c_accel_detect_vibration(void);   /* true if threshold exceeded */

#endif
