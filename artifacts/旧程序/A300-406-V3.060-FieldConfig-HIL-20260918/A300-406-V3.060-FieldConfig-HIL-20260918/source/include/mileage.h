#ifndef MILEAGE_H
#define MILEAGE_H
#include <stdint.h>
#include <stdbool.h>
void mileage_update(void);  /* call each time gps_process() runs */
void mileage_persist_process(uint32_t now_ms);
bool mileage_force_save(uint32_t now_ms);
#endif
