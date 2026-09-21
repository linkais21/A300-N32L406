#include "geofence.h"
#include "jt808.h"

void geofence_handle_jt808(const uint8_t *body, uint16_t len, uint16_t sn)
{
    (void)body;
    (void)len;
    (void)jt808_send_general_resp(sn, MSG_SET_POLYGON_AREA, 1);
}
