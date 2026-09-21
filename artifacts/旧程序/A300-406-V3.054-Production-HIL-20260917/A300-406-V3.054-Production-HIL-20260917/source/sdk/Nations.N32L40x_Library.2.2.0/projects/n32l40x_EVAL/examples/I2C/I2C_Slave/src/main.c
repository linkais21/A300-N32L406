/*****************************************************************************
 * Copyright (c) 2022, Nations Technologies Inc.
 *
 * All rights reserved.
 * ****************************************************************************
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * - Redistributions of source code must retain the above copyright notice,
 * this list of conditions and the disclaimer below.
 *
 * Nations' name may not be used to endorse or promote products derived from
 * this software without specific prior written permission.
 *
 * DISCLAIMER: THIS SOFTWARE IS PROVIDED BY NATIONS "AS IS" AND ANY EXPRESS OR
 * IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
 * MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NON-INFRINGEMENT ARE
 * DISCLAIMED. IN NO EVENT SHALL NATIONS BE LIABLE FOR ANY DIRECT, INDIRECT,
 * INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
 * OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
 * LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
 * NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
 * EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 * ****************************************************************************/

/**
 * @file main.c
 * @author Nations
 * @version V1.2.2
 *
 * @copyright Copyright (c) 2022, Nations Technologies Inc. All rights reserved.
 */
#include "n32l40x.h"
#include "n32l40x_i2c.h"
#include "main.h"
#include "log.h"
/** @addtogroup N32L40X_StdPeriph_Examples
 * @{
 */

/** @addtogroup I2C_Slave
 * @{
 */

#define TEST_BUFFER_SIZE  100
#define I2CT_FLAG_TIMEOUT ((uint32_t)0x1000)
#define I2CT_LONG_TIMEOUT ((uint32_t)(10 * I2CT_FLAG_TIMEOUT))
#define I2C_SLAVE_ADDR    0x10

#define I2C1_TEST
#define I2C1_REMAP
#define I2Cx I2C1
#define I2Cx_SCL_PIN GPIO_PIN_8
#define I2Cx_SDA_PIN GPIO_PIN_9
#define GPIOx        GPIOB

static uint8_t data_buf[TEST_BUFFER_SIZE] = {0};
static __IO uint32_t I2CTimeout;
static uint8_t rxDataNum = 0;

void CommTimeOut_CallBack(ErrCode_t errcode);

/**
 * @brief  I2C slave init
 *
 * @return 0:init finish
 */
int i2c_slave_init(void)
{
    I2C_InitType i2c1_slave;
    GPIO_InitType i2c1_gpio;
    // enable clk
    RCC_EnableAPB1PeriphClk(RCC_APB1_PERIPH_I2C1, ENABLE);
    RCC_EnableAPB2PeriphClk(RCC_APB2_PERIPH_AFIO, ENABLE);
    RCC_EnableAPB2PeriphClk(RCC_APB2_PERIPH_GPIOB, ENABLE);
    GPIOx->POD |= (I2Cx_SCL_PIN | I2Cx_SDA_PIN);//pull up pin

    /*PB8 -- SCL; PB9 -- SDA*/
    GPIO_InitStruct(&i2c1_gpio);
    i2c1_gpio.Pin               = I2Cx_SCL_PIN | I2Cx_SDA_PIN;
    i2c1_gpio.GPIO_Slew_Rate    = GPIO_Slew_Rate_High;
    i2c1_gpio.GPIO_Mode         = GPIO_Mode_AF_OD;
    i2c1_gpio.GPIO_Alternate    = GPIO_AF4_I2C1;
    i2c1_gpio.GPIO_Pull         = GPIO_Pull_Up;	  
    GPIO_InitPeripheral(GPIOx, &i2c1_gpio);

    I2C_DeInit(I2C1);
	I2C_InitStruct(&i2c1_slave);
    i2c1_slave.BusMode     = I2C_BUSMODE_I2C;
    i2c1_slave.FmDutyCycle = I2C_FMDUTYCYCLE_2;
    i2c1_slave.OwnAddr1    = I2C_SLAVE_ADDR;
    i2c1_slave.AckEnable   = I2C_ACKEN;
    i2c1_slave.AddrMode    = I2C_ADDR_MODE_7BIT;
    i2c1_slave.ClkSpeed    = 100000; // 100K

    I2C_Init(I2C1, &i2c1_slave);
    I2C_Enable(I2C1, ENABLE);
    return 0;
}

/**
 * @brief  I2C slave send data
 *
 * @param data data buffer
 * @param len send data len
 * @return 0:send finish
 */
int i2c_slave_send(uint8_t* data, int len)
{
    uint32_t lastevent;
    uint8_t* sendBufferPtr = data;
    I2CTimeout = I2CT_LONG_TIMEOUT*10;
    
    while (!I2C_CheckEvent(I2C1, I2C_EVT_SLAVE_SEND_ADDR_MATCHED))/* send addr matched */ 
    {
        if ((I2CTimeout--) == 0)
        {
            CommTimeOut_CallBack(SLAVE_MODE);
            return 1;
        }
    }
    I2CTimeout = I2CT_LONG_TIMEOUT;


    I2C_Enable(I2C1, ENABLE);
    I2C_SendData(I2C1, *sendBufferPtr++);
    while (1)
    {
        lastevent = I2C_GetLastEvent(I2C1);
        if (lastevent == I2C_EVT_SLAVE_DATA_SENDED)
        {
            I2C_SendData(I2C1, *sendBufferPtr++);
            I2CTimeout = I2CT_LONG_TIMEOUT;
        }
        else if ((lastevent == I2C_EVT_SLAVE_ACK_MISS) || (lastevent == I2C_EVT_SLAVE_STOP_RECVD))
        {
            I2C_ClrFlag(I2C1, I2C_FLAG_ACKFAIL);
            I2C_Enable(I2C1, ENABLE);
            break;
        }
        else if ((lastevent & 0x00000100) == 0x00000100)
        {
            CommTimeOut_CallBack(SLAVE_BUSERR);
            return 1;
        }
        else
        {
            if ((I2CTimeout--) == 0)
            {
                CommTimeOut_CallBack(SLAVE_UNKNOW);
                return 1;
            }
        }
    }
    return 0;
}

/**
 * @brief  I2C slave receive data
 *
 * @param data data buffer,use to save received data
 * @param rcv_len receive data len
 * @return 0:recv finish
 */
int i2c_slave_recv(uint8_t* data, uint32_t rcv_len)
{
    uint32_t lastevent;
    rxDataNum = 0;
    I2CTimeout = I2CT_LONG_TIMEOUT*10;
    
    while (!I2C_CheckEvent(I2C1, I2C_EVT_SLAVE_RECV_ADDR_MATCHED))/* receive addr matched */
    {
        if ((I2CTimeout--) == 0)
        {
            CommTimeOut_CallBack(SLAVE_MODE);
            return 1;
        }
    }
    I2CTimeout = I2CT_LONG_TIMEOUT;

    I2C_Enable(I2C1, ENABLE);
    while (1)
    {
        lastevent = I2C_GetLastEvent(I2C1);
        if (lastevent == I2C_EVT_SLAVE_DATA_RECVD)
        {
            *data++ = I2C_RecvData(I2C1);
            rxDataNum++;
            I2CTimeout = I2CT_LONG_TIMEOUT;
        }
        else if (lastevent == I2C_EVT_SLAVE_STOP_RECVD)
        {
            I2C_Enable(I2C1, ENABLE);
            break;
        }
        else if ((lastevent & 0x00000100) == 0x00000100)
        {
            CommTimeOut_CallBack(SLAVE_BUSERR);
            return 1;
        }
        else
        {
            if ((I2CTimeout--) == 0)
            {
                CommTimeOut_CallBack(SLAVE_UNKNOW);
                return 1;
            }
        }
    }
    
    return 0;
}

/**
 * @brief   Main program
 */
int main(void)
{
    uint16_t i = 0;

    log_init();
    log_info("\nthis is a i2c slave test demo\r\n");
    /* Initialize the I2C EEPROM driver ----------------------------------------*/
    i2c_slave_init();
    
    while (1)
    {
        for(; ;)
        {
            /* Read data */
            if(i2c_slave_recv(data_buf, TEST_BUFFER_SIZE))
            {
                break;  /* receive fail, reaccept*/
            }
            
            /* Write data*/
            if(i2c_slave_send(data_buf, TEST_BUFFER_SIZE))
            {
                break;  /* send fail, reaccept*/
            }
            for (i = 0; i < TEST_BUFFER_SIZE; i++)
            {
                data_buf[i] = 0;
            }
        }
    }
}
    
void SystemNVICReset(void)
{
    __set_FAULTMASK((uint32_t)1);
    log_info("***** NVIC system reset! *****\r\n");
    __NVIC_SystemReset();
}

void IIC_RCCReset(void)
{       
    RCC_EnableAPB1PeriphReset(RCC_APB1_PERIPH_I2C1, ENABLE);
    RCC_EnableAPB1PeriphReset(RCC_APB1_PERIPH_I2C1, DISABLE);
    
    i2c_slave_init();
    log_info("***** IIC module by RCC reset! *****\r\n");
    
}

void IIC_SWReset(void)
{
    GPIO_InitType i2cx_gpio;
    
    GPIO_InitStruct(&i2cx_gpio);
    i2cx_gpio.Pin               = I2Cx_SCL_PIN | I2Cx_SDA_PIN;
    i2cx_gpio.GPIO_Slew_Rate    = GPIO_Slew_Rate_High;
    i2cx_gpio.GPIO_Mode         = GPIO_Mode_Input;
    i2cx_gpio.GPIO_Alternate    = GPIO_NO_AF;
    i2cx_gpio.GPIO_Pull         = GPIO_No_Pull;	  
    GPIO_InitPeripheral(GPIOx, &i2cx_gpio);
    
    I2CTimeout = I2CT_LONG_TIMEOUT;
    for (;;)
    {
        if ((I2Cx_SCL_PIN | I2Cx_SDA_PIN) == (GPIOx->PID & (I2Cx_SCL_PIN | I2Cx_SDA_PIN)))
        {
            I2Cx->CTRL1 |= 0x8000;
            __NOP();
            __NOP();
            __NOP();
            __NOP();
            __NOP();
            I2Cx->CTRL1 &= ~0x8000;
            
            log_info("***** IIC module self reset! *****\r\n");
            break;
        }
        else
        {
            if ((I2CTimeout--) == 0)
            {
                IIC_RCCReset();
            }
        }
    }
}

void CommTimeOut_CallBack(ErrCode_t errcode)
{
    log_info("...ErrCode:%d\r\n", errcode);
    
#if (COMM_RECOVER_MODE == MODULE_SELF_RESET)
    IIC_SWReset();
#elif (COMM_RECOVER_MODE == MODULE_RCC_RESET)
    IIC_RCCReset();
#elif (COMM_RECOVER_MODE == SYSTEM_NVIC_RESET)
    SystemNVICReset();
#endif
}

/**
 * @}
 */
