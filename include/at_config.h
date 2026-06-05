#ifndef AT_CONFIG_H
#define AT_CONFIG_H

#include <stdint.h>

void at_config_init(void);
/* Feed one byte from debug/RS232 UART into the command parser */
void at_config_feed(uint8_t byte);
/* Process pending command (call from main loop) */
void at_config_process(void);

#endif
