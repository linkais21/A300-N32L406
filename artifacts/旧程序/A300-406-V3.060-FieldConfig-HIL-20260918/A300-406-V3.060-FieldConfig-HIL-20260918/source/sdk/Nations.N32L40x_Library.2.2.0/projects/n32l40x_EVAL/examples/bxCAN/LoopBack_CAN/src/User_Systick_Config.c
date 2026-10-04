#include "n32l40x.h"
#include "system_n32l40x.h"
#include "User_Systick_Config.h"

uint32_t systick_count;

/**
 * @brief  Systick Disable
 */
void Systick_Disable(void)
{
    SysTick->CTRL &= (~SysTick_CTRL_ENABLE_Msk); 
}


/**
 * @brief  Read User Time Since Last Set
 * @param last time.
 */
uint32_t User_Time_Read(uint32_t time)
{
    if(systick_count>=time)
    {
       return systick_count-time;
    }
    return(0xFFFFFFFF-time+systick_count);
}

/**
 * @brief  Set The User Time By Current  Value
 * @param set time.
 */
void User_Time_Set(uint32_t* time)
{
   *time=systick_count;
}
