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
 * @file usb_pwr.c
 * @author Nations
 * @version V1.2.2
 *
 * @copyright Copyright (c) 2022, Nations Technologies Inc. All rights reserved.
 */
#include "usb_lib.h"
#include "usb_conf.h"
#include "usb_pwr.h"
#include "hw_config.h"

typedef enum
{
    SYSCLK_PLLSRC_HSI,
    SYSCLK_PLLSRC_HSIDIV2,
    SYSCLK_PLLSRC_HSI_PLLDIV2,
    SYSCLK_PLLSRC_HSIDIV2_PLLDIV2,
    SYSCLK_PLLSRC_HSE,
    SYSCLK_PLLSRC_HSEDIV2,
    SYSCLK_PLLSRC_HSE_PLLDIV2,
    SYSCLK_PLLSRC_HSEDIV2_PLLDIV2,
}SYSCLK_PLL_TYPE;

__IO uint32_t bDeviceState = UNCONNECTED; /* USB device status */
__IO bool fSuspendEnabled  = true;        /* true when suspend is possible */
__IO uint32_t EP[8];

struct
{
    __IO RESUME_STATE eState;
    __IO uint8_t bESOFcnt;
} ResumeS;

__IO uint32_t remotewakeupon = 0;

extern uint32_t system_clock;

/* Extern function prototypes ------------------------------------------------*/

/**
 * @brief   PowerOn.
 * @return  Success.
 */
USB_Result PowerOn(void)
{
    uint16_t wRegVal;

    /*** CNTR_PWDN = 0 ***/
    wRegVal = CTRL_FRST;
    _SetCNTR(wRegVal);

    /*** CTRL_FRST = 0 ***/
    wInterrupt_Mask = 0;
    _SetCNTR(wInterrupt_Mask);
    /*** Clear pending interrupts ***/
    _SetISTR(0);
    /*** Set interrupt mask ***/
    wInterrupt_Mask = CTRL_RSTM | CTRL_SUSPDM | CTRL_WKUPM;
    _SetCNTR(wInterrupt_Mask);

    return Success;
}

/**
 * @brief   Handles switch-off conditions.
 * @return  Success.
 */
USB_Result PowerOff()
{
    /* disable all interrupts and force USB reset */
    _SetCNTR(CTRL_FRST);
    /* clear interrupt status register */
    _SetISTR(0);
    /* switch-off device */
    _SetCNTR(CTRL_FRST + CTRL_PD);
    /* sw variables reset */
    /* ... */

    return Success;
}

/**
 * @brief  set system clock with MSI.
 * @param void.
 */
void SetSysClock_MSI(void)
{
    if(RESET == RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_MSIRD))
    {
        /* Enable MSI and Config Clock */
        RCC_ConfigMsi(RCC_MSI_ENABLE, RCC_MSI_RANGE_4M);
        /* Waits for MSI start-up */
        while(SUCCESS != RCC_WaitMsiStable());
    }

    /* Enable Prefetch Buffer */
    FLASH_PrefetchBufSet(FLASH_PrefetchBuf_EN);

    /* Select MSI as system clock source */
    RCC_ConfigSysclk(RCC_SYSCLK_SRC_MSI);

    /* Wait till MSI is used as system clock source */
    while (RCC_GetSysclkSrc() != 0x00)
    {
        /* If this bits are always not set,
        it means system clock select MSI failed,
        user can add here some code to deal with this error */
    }

    /* HCLK = SYSCLK */
    RCC_ConfigHclk(RCC_SYSCLK_DIV1);

    /* PCLK2 = HCLK */
    RCC_ConfigPclk2(RCC_HCLK_DIV1);

    /* PCLK1 = HCLK */
    RCC_ConfigPclk1(RCC_HCLK_DIV1);
}

/**
 * @brief  Configures system clock after wake-up from low power mode: enable HSE, PLL
 *         and select PLL as system clock source.
 * @param  freq: PLL clock
 * @param  src 
 *   This parameter can be one of the following values:
 *     @arg SYSCLK_PLLSRC_HSI,
 *     @arg SYSCLK_PLLSRC_HSIDIV2,
 *     @arg SYSCLK_PLLSRC_HSI_PLLDIV2,
 *     @arg SYSCLK_PLLSRC_HSIDIV2_PLLDIV2,
 *     @arg SYSCLK_PLLSRC_HSE,
 *     @arg SYSCLK_PLLSRC_HSEDIV2,
 *     @arg SYSCLK_PLLSRC_HSE_PLLDIV2,
 *     @arg SYSCLK_PLLSRC_HSEDIV2_PLLDIV2,       
 */
void SetSysClockToPLL(uint32_t freq, SYSCLK_PLL_TYPE src)
{
    uint32_t pllsrcclk;
    uint32_t pllsrc;
    uint32_t pllmul;
    uint32_t plldiv = RCC_PLLDIVCLK_DISABLE;
    uint32_t latency;
    uint32_t pclk1div, pclk2div;
    uint32_t msi_ready_flag = RESET;
    ErrorStatus HSEStartUpStatus;
    ErrorStatus HSIStartUpStatus;
    
    
    if (HSE_VALUE != 8000000)
    {
        /* HSE_VALUE == 8000000 is needed in this project! */
        while (1);
    }

    /* SYSCLK, HCLK, PCLK2 and PCLK1 configuration
     * -----------------------------*/

    if ((src == SYSCLK_PLLSRC_HSI)         || (src == SYSCLK_PLLSRC_HSIDIV2) 
     || (src == SYSCLK_PLLSRC_HSI_PLLDIV2) || (src == SYSCLK_PLLSRC_HSIDIV2_PLLDIV2))
    {
        /* Enable HSI */
        RCC_ConfigHsi(RCC_HSI_ENABLE);

        /* Wait till HSI is ready */
        HSIStartUpStatus = RCC_WaitHsiStable();

        if (HSIStartUpStatus != SUCCESS)
        {
            /* If HSI fails to start-up, the application will have wrong clock
               configuration. User can add here some code to deal with this
               error */

            /* Go to infinite loop */
            while (1);
        }

        if ((src == SYSCLK_PLLSRC_HSIDIV2) || (src == SYSCLK_PLLSRC_HSIDIV2_PLLDIV2))
        {
            pllsrc = RCC_PLL_HSI_PRE_DIV2;
            pllsrcclk = HSI_VALUE/2;

            if(src == SYSCLK_PLLSRC_HSIDIV2_PLLDIV2)
            {
                plldiv = RCC_PLLDIVCLK_ENABLE;
                pllsrcclk = HSI_VALUE/4;
            }
        } else if ((src == SYSCLK_PLLSRC_HSI) || (src == SYSCLK_PLLSRC_HSI_PLLDIV2))
        {
            pllsrc = RCC_PLL_HSI_PRE_DIV1;
            pllsrcclk = HSI_VALUE;

            if(src == SYSCLK_PLLSRC_HSI_PLLDIV2)
            {
                plldiv = RCC_PLLDIVCLK_ENABLE;
                pllsrcclk = HSI_VALUE/2;
            }
        }

    } else if ((src == SYSCLK_PLLSRC_HSE)         || (src == SYSCLK_PLLSRC_HSEDIV2) 
            || (src == SYSCLK_PLLSRC_HSE_PLLDIV2) || (src == SYSCLK_PLLSRC_HSEDIV2_PLLDIV2))
    {
        /* Enable HSE */
        RCC_ConfigHse(RCC_HSE_ENABLE);

        /* Wait till HSE is ready */
        HSEStartUpStatus = RCC_WaitHseStable();

        if (HSEStartUpStatus != SUCCESS)
        {
            /* If HSE fails to start-up, the application will have wrong clock
               configuration. User can add here some code to deal with this
               error */

            /* Go to infinite loop */
            while (1);
        }

        if ((src == SYSCLK_PLLSRC_HSEDIV2) || (src == SYSCLK_PLLSRC_HSEDIV2_PLLDIV2))
        {
            pllsrc = RCC_PLL_SRC_HSE_DIV2;
            pllsrcclk = HSE_VALUE/2;

            if(src == SYSCLK_PLLSRC_HSEDIV2_PLLDIV2)
            {
                plldiv = RCC_PLLDIVCLK_ENABLE;
                pllsrcclk = HSE_VALUE/4;
            }
        } else if ((src == SYSCLK_PLLSRC_HSE) || (src == SYSCLK_PLLSRC_HSE_PLLDIV2))
        {
            pllsrc = RCC_PLL_SRC_HSE_DIV1;
            pllsrcclk = HSE_VALUE;

            if(src == SYSCLK_PLLSRC_HSE_PLLDIV2)
            {
                plldiv = RCC_PLLDIVCLK_ENABLE;
                pllsrcclk = HSE_VALUE/2;
            }
        }
    }

    latency = (freq/32000000);
    
    if(freq > 54000000)
    {
        pclk1div = RCC_HCLK_DIV4;
        pclk2div = RCC_HCLK_DIV2;
    }
    else
    {
        if(freq > 27000000)
        {
            pclk1div = RCC_HCLK_DIV2;
            pclk2div = RCC_HCLK_DIV1;
        }
        else
        {
            pclk1div = RCC_HCLK_DIV1;
            pclk2div = RCC_HCLK_DIV1;
        }
    }
    
    if(((freq % pllsrcclk) == 0) && ((freq / pllsrcclk) >= 2) && ((freq / pllsrcclk) <= 32))
    {
        pllmul = (freq / pllsrcclk);
        if(pllmul <= 16)
        {
            pllmul = ((pllmul - 2) << 18);
        }
        else
        {
            pllmul = (((pllmul - 17) << 18) | (1 << 27));
        }
    }
    else
    {
        /* User can add here some code to deal with this error */
        while(1);
    }

    /* Cheak if MSI is Ready */
    if(RESET == RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_MSIRD))
    {
        /* Enable MSI and Config Clock */
        RCC_ConfigMsi(RCC_MSI_ENABLE, RCC_MSI_RANGE_4M);
        /* Waits for MSI start-up */
        while(SUCCESS != RCC_WaitMsiStable());

        msi_ready_flag = SET;
    }

    /* Select MSI as system clock source */
    RCC_ConfigSysclk(RCC_SYSCLK_SRC_MSI);

    FLASH_SetLatency(latency);

    /* HCLK = SYSCLK */
    RCC_ConfigHclk(RCC_SYSCLK_DIV1);

    /* PCLK2 = HCLK */
    RCC_ConfigPclk2(pclk2div);

    /* PCLK1 = HCLK */
    RCC_ConfigPclk1(pclk1div);

    /* Disable PLL */
    RCC_EnablePll(DISABLE);

    RCC_ConfigPll(pllsrc, pllmul, plldiv);

    /* Enable PLL */
    RCC_EnablePll(ENABLE);

    /* Wait till PLL is ready */
    while (RCC_GetFlagStatus(RCC_CTRL_FLAG_PLLRDF) == RESET); /* If this flag is always not set, it means PLL is failed, user can add here some code to deal with this error */

    /* Select PLL as system clock source */
    RCC_ConfigSysclk(RCC_SYSCLK_SRC_PLLCLK);

    /* Wait till PLL is used as system clock source */
    while (RCC_GetSysclkSrc() != 0x0C); /* If this bits are always not set, it means system clock select PLL failed, user can add here some code to deal with this error */

    if(msi_ready_flag == SET)
    {
        /* MSI oscillator OFF */
        RCC_ConfigMsi(RCC_MSI_DISABLE, RCC_MSI_RANGE_4M);
    }
}


/**
 * @brief   Sets suspend mode operating conditions
 */
void Suspend(void)
{
    uint32_t i = 0;
    uint16_t wCNTR;
        
    /* suspend preparation */
    /* ... */

#if (XTALLESS == 1)
    RCC->APB1PRST |= RCC_APB1PRST_UCDRRST;
    RCC->APB1PRST &= ~RCC_APB1PRST_UCDRRST;
#endif

    /*Store CTRL value */
    wCNTR = _GetCNTR();

    /* This a sequence to apply a force RESET to handle a robustness case */

    /*Store endpoints registers status */
    for (i = 0; i < 8; i++)
        EP[i] = _GetENDPOINT(i);

    /* unmask RESET flag */
    wCNTR |= CTRL_RSTM;
    _SetCNTR(wCNTR);

    /*apply FRES */
    wCNTR |= CTRL_FRST;
    _SetCNTR(wCNTR);

    /*clear FRES*/
    wCNTR &= ~CTRL_FRST;
    _SetCNTR(wCNTR);

    /* poll for RESET flag in STS, this bit will be set by hardware, if this flag is always not set, it means maybe USB module failure */
    while ((_GetISTR() & STS_RST) == 0);

    /* clear RESET flag in STS */
    _SetISTR((uint16_t)CLR_RST);

    /*restore Enpoints*/
    for (i = 0; i < 8; i++)
        _SetENDPOINT(i, EP[i]);

    /* Now it is safe to enter macrocell in suspend mode */
    wCNTR |= CTRL_FSUSPD;
    _SetCNTR(wCNTR);

    /* force low-power mode in the macrocell */
    wCNTR = _GetCNTR();
    wCNTR |= CTRL_LP_MODE;
    _SetCNTR(wCNTR);

#ifdef USB_LOW_PWR_MGMT_SUPPORT
	/* Before entering LP RUN mode, you must make sure that the system clock is less
        than or equal to 4MHz. This project takes configuring MSI (4MHz) as an example, 
        and users can configure other clock sources as system clock as needed */
    SetSysClock_MSI();
	
    /* Request to enter LP SLEEP mode*/
    PWR_EnterLowPowerSleepMode(SLEEP_OFF_EXIT, PWR_SLEEPENTRY_WFI);
	
    /* Exit LP SLEEP mode*/
    PWR_ExitLowPowerRunMode();
	SetSysClockToPLL(system_clock,SYSCLK_PLLSRC_HSE);
    USB_Config(system_clock);
#endif  /* USB_LOW_PWR_MGMT_SUPPORT */
}

/**
 * @brief   Handles wake-up restoring normal operations
 */
void Resume_Init(void)
{
    uint16_t wCNTR;

    /* ------------------ ONLY WITH BUS-POWERED DEVICES ---------------------- */
    /* restart the clocks */
    /* ...  */

    /* CTRL_LP_MODE = 0 */
    wCNTR = _GetCNTR();
    wCNTR &= (~CTRL_LP_MODE);
    _SetCNTR(wCNTR);

#ifdef USB_LOW_PWR_MGMT_SUPPORT      
    /* restore full power */
    /* ... on connected devices */
    Leave_LowPowerMode();
#endif /* USB_LOW_PWR_MGMT_SUPPORT */

    /* reset FSUSP bit */
    _SetCNTR(IMR_MSK);

    /* reverse suspend preparation */
    /* ... */
}

/**
 * @brief   This is the state machine handling resume operations and
 *                 timing sequence. The control is based on the Resume structure
 *                 variables and on the ESOF interrupt calling this subroutine
 *                 without changing machine state.
 * @param   eResumeSetVal: a state machine value (RESUME_STATE)
 *                         RESUME_ESOF doesn't change ResumeS.eState allowing
 *                         decrementing of the ESOF counter in different states.
 */
void Resume(RESUME_STATE eResumeSetVal)
{
    uint16_t wCNTR;

    if (eResumeSetVal != RESUME_ESOF)
        ResumeS.eState = eResumeSetVal;
    switch (ResumeS.eState)
    {
    case RESUME_EXTERNAL:
        if (remotewakeupon == 0)
        {
            Resume_Init();
            ResumeS.eState = RESUME_OFF;
        }
        else /* RESUME detected during the RemoteWAkeup signalling => keep RemoteWakeup handling*/
        {
            ResumeS.eState = RESUME_ON;
        }
        break;
    case RESUME_INTERNAL:
        Resume_Init();
        ResumeS.eState = RESUME_START;
        remotewakeupon = 1;
        break;
    case RESUME_LATER:
        ResumeS.bESOFcnt = 2;
        ResumeS.eState   = RESUME_WAIT;
        break;
    case RESUME_WAIT:
        ResumeS.bESOFcnt--;
        if (ResumeS.bESOFcnt == 0)
            ResumeS.eState = RESUME_START;
        break;
    case RESUME_START:
        wCNTR = _GetCNTR();
        wCNTR |= CTRL_RESUM;
        _SetCNTR(wCNTR);
        ResumeS.eState   = RESUME_ON;
        ResumeS.bESOFcnt = 10;
        break;
    case RESUME_ON:
        ResumeS.bESOFcnt--;
        if (ResumeS.bESOFcnt == 0)
        {
            wCNTR = _GetCNTR();
            wCNTR &= (~CTRL_RESUM);
            _SetCNTR(wCNTR);
            ResumeS.eState = RESUME_OFF;
            remotewakeupon = 0;
        }
        break;
    case RESUME_OFF:
    case RESUME_ESOF:
    default:
        ResumeS.eState = RESUME_OFF;
        break;
    }
}

/**
 * @}
 */

/**
 * @}
 */

/**
 * @}
 */
