/* Dependencies outside the JT808 unit boundary. Tests exercising the real
 * subsystem omit the corresponding stub instead of replacing production code. */
#ifndef JT808_HOST_SUPPORT_H
#define JT808_HOST_SUPPORT_H
#include <string.h>
#include "fota.h"
#include "gps.h"
#include "at_config.h"
#ifndef HOST_REAL_GPS
void gps_get_unfixed_report(gps_data_t *out) { memset(out, 0, sizeof(*out)); }
#endif
fota_state_t fota_get_state(void) { return FOTA_STATE_IDLE; }
bool gps_report_filter_motion_pending(uint32_t now) { (void)now; return false; }
void gps_report_filter_motion_ack(void) {}
void ec800m_tcp_close(uint8_t ch) { (void)ch; }
#ifndef HOST_REAL_AT_CONFIG
bool at_config_execute_text_response(const uint8_t *text, uint16_t len,
    at_config_text_ack_fn ack, at_config_text_reply_fn reply, void *context)
{
    (void)reply;
    return at_config_execute_text_command_ack(text, len, ack, context);
}
#endif
#endif
