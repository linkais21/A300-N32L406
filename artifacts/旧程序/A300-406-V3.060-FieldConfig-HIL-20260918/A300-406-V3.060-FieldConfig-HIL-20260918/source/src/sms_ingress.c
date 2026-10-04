#include "sms_ingress.h"
#include "sms_command.h"
#include <string.h>

static sms_ingress_cb_t s_callback;
static char s_from[SMS_PHONE_MAX_LEN];
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
    if (!s_pending) return;
    if (line[0] == '+' || strcmp(line, "OK") == 0 || strcmp(line, "ERROR") == 0 || strcmp(line, "RDY") == 0) { s_pending = false; return; }
    while (len < SMS_COMMAND_MAX_LEN && line[len] != '\0') ++len;
    /* SMS command text is terminated by '#'; reject unframed modem chatter. */
    if (len >= 2 && len < SMS_COMMAND_MAX_LEN && line[len - 1] == '#')
        (void)sms_queue_push(s_from, (const uint8_t *)line, (uint16_t)(len - 1));
    s_pending = false;
}

void sms_ingress_process(void)
{
    char from[SMS_PHONE_MAX_LEN];
    uint8_t cmd[SMS_COMMAND_MAX_LEN];
    uint16_t len;
    if (!s_callback || !sms_queue_pop(from, sizeof(from), cmd, sizeof(cmd), &len)) return;
    s_callback(from, cmd, len);
}
