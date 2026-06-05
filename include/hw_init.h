#ifndef HW_INIT_H
#define HW_INIT_H

#include <stdint.h>

void hw_clock_init(void);    /* 64 MHz via HSI PLL */
void hw_gpio_init(void);
void hw_usart_init(void);    /* USART1(debug) USART2(GPS) USART3(EC800M) */
void hw_spi_init(void);      /* SPI1 for BY25Q16 flash */
void hw_i2c_init(void);      /* I2C1 for DA218E + N32S003 */
void hw_adc_init(void);      /* ADC1 ch1(car) ch2(bat) */
void hw_tim_init(void);      /* TIM8 1ms base tick */
void hw_iwdg_init(void);
void hw_nvic_init(void);

void delay_ms(uint32_t ms);
void delay_us(uint32_t us);

#endif
