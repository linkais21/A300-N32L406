#include "sms_ingress.h"
#include "sms_command.h"
#include <string.h>

static sms_ingress_cb_t s_callback;
static char s_from[20];
static bool s_pending;

void sms_ingress_set_callback(sms_ingress_cb_t cb) { s_callback = cb; }

void sms_ingress_feed_line(const char *line)
{
    const char *q1;
    const char *q2;
    uint16_t len = 0;
    if (!line) return;
    if (strncmp(line, "+CMT:", 5) == 0) {
        q1 = strchr(line, '"');
        q2 = q1 ? strchr(q1 + 1, '"') : 0;
        if (!q2 || (uint16_t)(q2 - q1 - 1) >= sizeof(s_from)) { s_pending = false; return; }
        memcpy(s_from, q1 + 1, (uint16_t)(q2 - q1 - 1));
        s_from[q2 - q1 - 1] = '\0';
        s_pending = true;
        return;
    }
    if (!s_pending || line[0] == '+') return;
    while (len < SMS_COMMAND_MAX_LEN && line[len] != '\0') ++len;
    if (len < SMS_COMMAND_MAX_LEN) (void)sms_queue_push((const uint8_t *)line, len);
    s_pending = false;
}

void sms_ingress_process(void)
{
    uint8_t cmd[SMS_COMMAND_MAX_LEN];
    uint16_t len;
    if (!s_callback || !sms_queue_pop(cmd, sizeof(cmd), &len)) return;
    s_callback(s_from, cmd, len);
}
