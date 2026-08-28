#include "sms_command.h"
#include <string.h>
typedef struct { uint16_t len; uint8_t data[SMS_COMMAND_MAX_LEN]; } sms_queue_entry_t;
static sms_queue_entry_t s_queue[SMS_QUEUE_DEPTH];
static uint8_t s_head, s_tail, s_count;
static char upper(char c) { return (c >= 'a' && c <= 'z') ? (char)(c - 32) : c; }
static bool eq(const char *s, uint16_t n, const char *r) { uint16_t i=0; while (r[i]) { if (i>=n || upper(s[i])!=r[i]) return false; ++i; } return i==n; }
static bool root_ok(const char *s, uint16_t n)
{
    static const char *const roots[]={"PARAM","RESET","PID","IP","FIP","FREQ","HBT","MODEL","SPEED","APN","RELAY","GPSDUP","MLG","CAR","GPSBDS","GMTSET"};
    uint16_t i;
    for (i = 0; i < sizeof(roots) / sizeof(roots[0]); ++i)
        if (eq(s, n, roots[i])) return true;
    return false;
}
bool sms_command_allowed(const char *cmd)
{
    uint16_t n=0, root=0, nested=0;
    if (!cmd) return false;
    while (n < SMS_COMMAND_MAX_LEN && cmd[n]) ++n;
    if (!n || n == SMS_COMMAND_MAX_LEN) return false;
    while (root < n && cmd[root] != '=' && cmd[root] != ':' && cmd[root] != '?') ++root;
    if (!root) return false;
    if (eq(cmd, root, "DUALSET")) {
        const char *p;
        if (cmd[root] != '=') return false;
        p = cmd + root + 1;
        while (nested < n - root - 1 && p[nested] != '=' && p[nested] != ':' && p[nested] != '?') ++nested;
        return nested && root_ok(p, nested);
    }
    return root_ok(cmd, root);
}
bool sms_queue_push(const uint8_t *data, uint16_t len) {
    sms_queue_entry_t *e; if(!data || !len || len>=SMS_COMMAND_MAX_LEN || s_count>=SMS_QUEUE_DEPTH) return false;
    e=&s_queue[s_tail]; memcpy(e->data,data,len); e->data[len]=0; if(!sms_command_allowed((const char*)e->data)) return false; e->len=len; s_tail=(uint8_t)((s_tail+1)%SMS_QUEUE_DEPTH); ++s_count; return true;
}
bool sms_queue_pop(uint8_t *out, uint16_t size, uint16_t *len) {
    sms_queue_entry_t *e; if(!out || !len || !s_count) return false; e=&s_queue[s_head]; if(size<e->len) return false; memcpy(out,e->data,e->len); *len=e->len; s_head=(uint8_t)((s_head+1)%SMS_QUEUE_DEPTH); --s_count; return true;
}
void sms_queue_reset(void) { s_head=s_tail=s_count=0; }
