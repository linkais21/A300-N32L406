#include "relay.h"
#include "config.h"
#include "n32l40x.h"
static bool s_state = false;
void relay_set(bool on)
{
    s_state = on;
    if (on) GPIO_SetBits(RELAY_PORT, RELAY_PIN);
    else    GPIO_ResetBits(RELAY_PORT, RELAY_PIN);
}
bool relay_get(void) { return s_state; }
