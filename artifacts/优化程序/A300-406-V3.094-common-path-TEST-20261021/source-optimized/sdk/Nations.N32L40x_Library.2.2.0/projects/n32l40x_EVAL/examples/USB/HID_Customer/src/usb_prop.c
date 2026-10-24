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
 * @file usb_prop.c
 * @author Nations
 * @version V1.2.2
 *
 * @copyright Copyright (c) 2022, Nations Technologies Inc. All rights reserved.
 */
/* Includes ------------------------------------------------------------------*/
#include "usb_lib.h"
#include "usb_conf.h"
#include "usb_prop.h"
#include "usb_desc.h"
#include "usb_pwr.h"
#include "hw_config.h"

/* Private typedef -----------------------------------------------------------*/
/* Private define ------------------------------------------------------------*/
/* Private macro -------------------------------------------------------------*/
/* Private variables ---------------------------------------------------------*/
uint32_t ProtocolValue;
__IO uint8_t EXTI_Enable;
__IO uint8_t Request = 0;
uint8_t Report_Buf[2];
/* -------------------------------------------------------------------------- */
/*  Structures initializations */
/* -------------------------------------------------------------------------- */

USB_Device Device_Table = {EP_NUM, 1};

DEVICE_PROP Device_Property = {
    CustomHID_init,
    CustomHID_Reset,
    CustomHID_Status_In,
    CustomHID_Status_Out,
    CustomHID_Data_Setup,
    CustomHID_NoData_Setup,
    CustomHID_Get_Interface_Setting,
    CustomHID_GetDeviceDescriptor,
    CustomHID_GetConfigDescriptor,
    CustomHID_GetStringDescriptor,
    0,
    0x40 /*MAX PACKET SIZE*/
};
USER_STANDARD_REQUESTS User_Standard_Requests = {CustomHID_GetConfiguration,
                                                 CustomHID_SetConfiguration,
                                                 CustomHID_GetInterface,
                                                 CustomHID_SetInterface,
                                                 CustomHID_GetStatus,
                                                 CustomHID_ClearFeature,
                                                 CustomHID_SetEndPointFeature,
                                                 CustomHID_SetDeviceFeature,
                                                 CustomHID_SetDeviceAddress};

USB_OneDescriptor Device_Descriptor = {(uint8_t*)CustomHID_DeviceDescriptor, CUSTOMHID_SIZ_DEVICE_DESC};

USB_OneDescriptor Config_Descriptor = {(uint8_t*)CustomHID_ConfigDescriptor, CUSTOMHID_SIZ_CONFIG_DESC};

USB_OneDescriptor CustomHID_Report_Descriptor = {(uint8_t*)CustomHID_ReportDescriptor, CUSTOMHID_SIZ_REPORT_DESC};

USB_OneDescriptor CustomHID_Hid_Descriptor = {(uint8_t*)CustomHID_ConfigDescriptor + CUSTOMHID_OFF_HID_DESC,
                                              CUSTOMHID_SIZ_HID_DESC};

USB_OneDescriptor String_Descriptor[4] = {{(uint8_t*)CustomHID_StringLangID, CUSTOMHID_SIZ_STRING_LANGID},
                                          {(uint8_t*)CustomHID_StringVendor, CUSTOMHID_SIZ_STRING_VENDOR},
                                          {(uint8_t*)CustomHID_StringProduct, CUSTOMHID_SIZ_STRING_PRODUCT},
                                          {(uint8_t*)CustomHID_StringSerial, CUSTOMHID_SIZ_STRING_SERIAL}};

/*CustomHID_SetReport_Feature function prototypes*/
uint8_t* CustomHID_SetReport_Feature(uint16_t Length);

/**
*\*\name    CustomHID_init.
*\*\fun     Custom HID init routine.
*\*\param   none
*\*\return  none 
**/
void CustomHID_init(void)
{
    /* Update the serial number string descriptor with the data from the unique
    ID*/
    pInformation->CurrentConfiguration = 0;
    /* Connect the device */
    PowerOn();

    /* Perform basic device initialization operations */
    USB_SilInit();
    
    /*Pull up DP*/
    _EnPortPullup();

    bDeviceState = UNCONNECTED;
}

/**
*\*\name    CustomHID_Reset.
*\*\fun     Custom HID reset routine.
*\*\param   none
*\*\return  none 
**/
void CustomHID_Reset(void)
{
    /* Set CustomHID_DEVICE as not configured */
    pInformation->CurrentConfiguration = 0;
    pInformation->CurrentInterface     = 0; /*the default Interface*/

    /* Current Feature initialization */
    pInformation->CurrentFeature = CustomHID_ConfigDescriptor[7];

    USB_SetBuftab(BTABLE_ADDRESS);

    /* Initialize Endpoint 0 */
    USB_SetEpType(ENDP0, EP_CONTROL);
    SetEPTxStatus(ENDP0, EP_TX_STALL);
    USB_SetEpRxAddr(ENDP0, ENDP0_RXADDR);
    USB_SetEpTxAddr(ENDP0, ENDP0_TXADDR);
    USB_ClrStsOut(ENDP0);
    USB_SetEpRxCnt(ENDP0, Device_Property.MaxPacketSize);
    USB_SetEpRxValid(ENDP0);

    /* Initialize Endpoint 1 */
    USB_SetEpType(ENDP1, EP_INTERRUPT);
    USB_SetEpTxAddr(ENDP1, ENDP1_TXADDR);
    USB_SetEpRxAddr(ENDP1, ENDP1_RXADDR);
    USB_SetEpTxCnt(ENDP1, 8);
    USB_SetEpRxCnt(ENDP1, 8);
    SetEPRxStatus(ENDP1, EP_RX_VALID);
    SetEPTxStatus(ENDP1, EP_TX_VALID);

    /* Set this device to response on default address */
    USB_SetDeviceAddress(0);
    bDeviceState = ATTACHED;
}

/**
*\*\name    CustomHID_SetConfiguration.
*\*\fun     Update the device state to configured.
*\*\param   none
*\*\return  none 
**/
void CustomHID_SetConfiguration(void)
{
    if (pInformation->CurrentConfiguration != 0)
    {
        /* Device configured */
        bDeviceState = CONFIGURED;
    }
}

/**
*\*\name    CustomHID_SetDeviceAddress.
*\*\fun     Update the device state to addressed.
*\*\param   none
*\*\return  none 
**/
void CustomHID_SetDeviceAddress(void)
{
    bDeviceState = ADDRESSED;
}

/**
*\*\name    CustomHID_Status_In.
*\*\fun     Keyboard status IN routine.
*\*\param   none
*\*\return  none 
**/
void CustomHID_Status_In(void)
{
}

/**
*\*\name    CustomHID_Status_Out.
*\*\fun     Keyboard status OUT routine.
*\*\param   none
*\*\return  none 
**/
void CustomHID_Status_Out(void)
{
}

/**
*\*\name    CustomHID_Data_Setup.
*\*\fun     Handle the data class specific requests.
*\*\param   RequestNo
*\*\            - GET_DESCRIPTOR
*\*\            - GET_PROTOCOL
*\*\            - SET_REPORT
*\*\return  USB_Result
*\*\            - Success
*\*\            - UnSupport
**/
USB_Result CustomHID_Data_Setup(uint8_t RequestNo)
{
    uint8_t* (*CopyRoutine)(uint16_t);

    if (pInformation->USBwIndex != 0)
        return UnSupport;

    CopyRoutine = NULL;

    if ((RequestNo == GET_DESCRIPTOR) && (Type_Recipient == (STANDARD_REQUEST | INTERFACE_RECIPIENT)))
    {
        if (pInformation->USBwValue1 == REPORT_DESCRIPTOR)
        {
            CopyRoutine = CustomHID_GetReportDescriptor;
        }
        else if (pInformation->USBwValue1 == HID_DESCRIPTOR_TYPE)
        {
            CopyRoutine = CustomHID_GetHIDDescriptor;
        }

    } /* End of GET_DESCRIPTOR */

    /*** GET_PROTOCOL, GET_REPORT, SET_REPORT ***/
    else if ((Type_Recipient == (CLASS_REQUEST | INTERFACE_RECIPIENT)))
    {
        switch (RequestNo)
        {
        case GET_PROTOCOL:
            CopyRoutine = CustomHID_GetProtocolValue;
            break;
        case SET_REPORT:
            CopyRoutine = CustomHID_SetReport_Feature;
            Request     = SET_REPORT;
            break;
        default:
            break;
        }
    }

    if (CopyRoutine == NULL)
    {
        return UnSupport;
    }

    pInformation->Ctrl_Info.CopyData    = CopyRoutine;
    pInformation->Ctrl_Info.Usb_wOffset = 0;
    (*CopyRoutine)(0);
    return Success;
}

/**
*\*\name    CustomHID_SetReport_Feature.
*\*\fun     Set Feature request handling.
*\*\param   Length: data length.
*\*\return  Report_Buf or NULL
**/
uint8_t* CustomHID_SetReport_Feature(uint16_t Length)
{
    if (Length == 0)
    {
        pInformation->Ctrl_Info.Usb_wLength = 2;
        return NULL;
    }
    else
    {
        return Report_Buf;
    }
}

/**
*\*\name    CustomHID_NoData_Setup.
*\*\fun     handle the no data class specific requests.
*\*\param   RequestNo: request number.
*\*\return  USB_Result
*\*\            - UnSupport
*\*\            - Success
**/
USB_Result CustomHID_NoData_Setup(uint8_t RequestNo)
{
    if ((Type_Recipient == (CLASS_REQUEST | INTERFACE_RECIPIENT)) && (RequestNo == SET_PROTOCOL))
    {
        return CustomHID_SetProtocol();
    }

    else
    {
        return UnSupport;
    }
}

/**
*\*\name    CustomHID_GetDeviceDescriptor.
*\*\fun     Gets the device descriptor.
*\*\param   Length: data length.
*\*\return  The address of the device descriptor.
**/
uint8_t* CustomHID_GetDeviceDescriptor(uint16_t Length)
{
    return Standard_GetDescriptorData(Length, &Device_Descriptor);
}

/**
*\*\name    CustomHID_GetConfigDescriptor.
*\*\fun     Gets the configuration descriptor.
*\*\param   Length: data length.
*\*\return  The address of the configuration descriptor.
**/
uint8_t* CustomHID_GetConfigDescriptor(uint16_t Length)
{
    return Standard_GetDescriptorData(Length, &Config_Descriptor);
}

/**
*\*\name    CustomHID_GetStringDescriptor.
*\*\fun     Gets the string descriptors according to the needed index.
*\*\param   Length: data length.
*\*\return  The address of the string descriptor.
**/
uint8_t* CustomHID_GetStringDescriptor(uint16_t Length)
{
    uint8_t wValue0 = pInformation->USBwValue0;
    if (wValue0 >= 4)
    {
        return NULL;
    }
    else
    {
        return Standard_GetDescriptorData(Length, &String_Descriptor[wValue0]);
    }
}

/**
*\*\name    CustomHID_GetReportDescriptor.
*\*\fun     Gets the HID report descriptor.
*\*\param   Length: data length.
*\*\return  The address of the report descriptor.
**/
uint8_t* CustomHID_GetReportDescriptor(uint16_t Length)
{
    return Standard_GetDescriptorData(Length, &CustomHID_Report_Descriptor);
}

/**
*\*\name    CustomHID_GetHIDDescriptor.
*\*\fun     Gets the HID descriptor.
*\*\param   Length: data length.
*\*\return  The address of the descriptor descriptor.
**/
uint8_t* CustomHID_GetHIDDescriptor(uint16_t Length)
{
    return Standard_GetDescriptorData(Length, &CustomHID_Hid_Descriptor);
}

/**
*\*\name    CustomHID_Get_Interface_Setting.
*\*\fun     tests the interface and the alternate setting according to the supported one.
*\*\param   Interface: interface number.
*\*\param   AlternateSetting: Alternate Setting number.
*\*\return  USB_Result
*\*\            - Success 
*\*\            - UnSupport.
**/
USB_Result CustomHID_Get_Interface_Setting(uint8_t Interface, uint8_t AlternateSetting)
{
    if (AlternateSetting > 0)
    {
        return UnSupport;
    }
    else if (Interface > 0)
    {
        return UnSupport;
    }
    return Success;
}

/**
*\*\name    CustomHID_SetProtocol.
*\*\fun     Set Protocol request routine.
*\*\param   none
*\*\return  USB_Result
*\*\            - Success 
*\*\            - UnSupport.
**/
USB_Result CustomHID_SetProtocol(void)
{
    uint8_t wValue0 = pInformation->USBwValue0;
    ProtocolValue   = wValue0;
    return Success;
}

/**
*\*\name    CustomHID_GetProtocolValue.
*\*\fun     get the protocol value.
*\*\param   Length: data length.
*\*\return  address of the protocol value.
**/
uint8_t* CustomHID_GetProtocolValue(uint16_t Length)
{
    if (Length == 0)
    {
        pInformation->Ctrl_Info.Usb_wLength = 1;
        return NULL;
    }
    else
    {
        return (uint8_t*)(&ProtocolValue);
    }
}
