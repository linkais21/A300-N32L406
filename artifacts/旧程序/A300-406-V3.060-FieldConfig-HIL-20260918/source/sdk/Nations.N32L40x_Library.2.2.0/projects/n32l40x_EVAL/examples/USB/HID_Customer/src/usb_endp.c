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
 * @file usb_endp.c
 * @author Nations
 * @version V1.2.2
 *
 * @copyright Copyright (c) 2022, Nations Technologies Inc. All rights reserved.
 */
/* Includes ------------------------------------------------------------------*/
#include "hw_config.h"
#include "usb_lib.h"
#include "usb_istr.h"

uint8_t Receive_Buffer[2];
extern __IO uint8_t PrevXferComplete;
extern u8* Ep1DataPtr;
extern u8 key_buffer[8];

/**
*\*\name    EP1_OUT_Callback.
*\*\fun     EP1 OUT Callback Routine.
*\*\param   none
*\*\return  none 
**/
void EP1_OUT_Callback(void)
{
    Bit_OperateType Led_State;

    /* Read received data (2 bytes) */  
    USB_SilRead(EP1_OUT, Receive_Buffer);

    if (Receive_Buffer[1] == 0)
    {
        Led_State = Bit_RESET;
    }
    else 
    {
        Led_State = Bit_SET;
    }

    switch (Receive_Buffer[0])
    {
    case 1: /* Led 1 */
        if (Led_State != Bit_RESET)
        {
        LedOn(LED1_PORT, LED1_PIN);
        }
        else
        {
        LedOff(LED1_PORT, LED1_PIN);
        }
        break;
    case 2: /* Led 2 */
        if (Led_State != Bit_RESET)
        {
        LedOn(LED2_PORT, LED2_PIN);
        }
        else
        {
        LedOff(LED2_PORT, LED2_PIN);
        }
        break;
    case 3: /* Led 3 */
        if (Led_State != Bit_RESET)
        {
            LedOn(LED3_PORT, LED3_PIN);
        }
        else
        {
            LedOff(LED3_PORT, LED3_PIN);
        }
        break;
    default:
        LedOff(LED1_PORT, LED1_PIN);
        LedOff(LED2_PORT, LED2_PIN);
        LedOff(LED3_PORT, LED3_PIN);
        break;
    }

    /* Enable the receive of data on EP1 */
    SetEPRxStatus(ENDP1, EP_RX_VALID);
}

/**
*\*\name    EP1_IN_Callback.
*\*\fun     EP1 IN Callback Routine.
*\*\param   none
*\*\return  none 
**/
void EP1_IN_Callback(void)
{
    PrevXferComplete = 1;
}

