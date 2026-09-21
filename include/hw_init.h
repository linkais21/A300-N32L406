#ifndef HW_INIT_H
#define HW_INIT_H

#include <stdint.h>
#include <stdbool.h>

void hw_clock_init(void);    /* 64 MHz via HSI PLL */
void hw_gpio_init(void);
void hw_usart_init(void);    /* USART1(debug/PA9/PA10) UART4(GPS/PB0/PB1) UART5(EC800M/PB4/PB5) */
void hw_spi_init(void);      /* SPI1 for BY25Q16 flash */
void hw_i2c_init(void);      /* I2C2 for DA218E on PD14/PD15 */
void hw_adc_init(void);      /* ADC ch4(PA3 car) ch2(PA1 bat) */
void hw_tim_init(void);      /* TIM8 1ms base tick */
void hw_iwdg_init(void);
void hw_nvic_init(void);
bool hw_acc_is_on(void); /* Q9-inverted PA12: physical low means ACC ON. */
bool hw_acc_pin_high(void);

void delay_ms(uint32_t ms);
void delay_us(uint32_t us);

#endif
