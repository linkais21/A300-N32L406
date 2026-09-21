#include "f39_reply.h"
#include "terminal_identity.h"

#include <stdarg.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static void reply_clear(f39_reply_t *reply)
{
    if (reply != NULL) {
        reply->len = 0U;
        reply->data[0] = '\0';
        reply->reset_pending = false;
        reply->reset_delay_ms = 0U;
    }
}

static bool reply_append(f39_reply_t *reply, const char *format, ...)
{
    va_list ap;
    int n;

    if (reply == NULL || format == NULL || reply->len >= F39_REPLY_MAX_LENGTH) {
        return false;
    }
    va_start(ap, format);
    n = vsnprintf((char *)&reply->data[reply->len],
                  F39_REPLY_MAX_LENGTH - reply->len, format, ap);
    va_end(ap);
    if (n < 0 || (uint32_t)n >= (uint32_t)(F39_REPLY_MAX_LENGTH - reply->len)) {
        reply->len = 0U;
        reply->data[0] = '\0';
        return false;
    }
    reply->len = (uint16_t)(reply->len + (uint16_t)n);
    return true;
}

static bool arg_text(const f39_request_t *request, uint8_t index,
                     char *buffer, uint16_t capacity)
{
    uint32_t end;
    uint16_t len;

    if (request == NULL || buffer == NULL || capacity == 0U ||
        index >= request->argc) {
        return false;
    }
    len = request->args[index].len;
    end = (uint32_t)request->args[index].offset + len;
    if (end > request->raw_len || len >= capacity) {
        return false;
    }
    (void)memcpy(buffer, &request->raw[request->args[index].offset], len);
    buffer[len] = '\0';
    return true;
}

static f39_result_t failure(f39_reply_t *reply, const char *name,
                            const char *reason)
{
    reply_clear(reply);
    (void)reply_append(reply, "%s=Fail! %s\r\n", name, reason);
    return F39_RESULT_INVALID;
}

static f39_result_t success(f39_reply_t *reply, const char *name)
{
    reply_clear(reply);
    if (!reply_append(reply, "%s=Success!\r\n", name)) {
        return F39_RESULT_INVALID;
    }
    return F39_RESULT_OK;
}

static bool operation_name(f39_operation_t operation, const char **name)
{
    static const char *const names[] = {
        "", "PARAM", "DUALSET", "RESET", "PID", "IP", "FIP", "FREQ",
        "HBT", "MODEL", "SPEED", "APN", "RELAY", "GPSDUP", "MLG",
        "CAR", "GPSBDS", "GMTSET", "VIBSENS", "FKEY", "FOTA", "LOG"
    };
    if (name == NULL || operation <= F39_OPERATION_INVALID ||
        operation > F39_OPERATION_LOG) {
        return false;
    }
    *name = names[operation];
    return true;
}

static void apply_effects(uint32_t effects, f39_platform_t *p)
{
    if ((effects & F39_EFFECT_TIMER_REFRESH) != 0U && p->timer_refresh != NULL) {
        p->timer_refresh(p->context);
    }
    if ((effects & (F39_EFFECT_MAIN_AUTH_RESET |
                    F39_EFFECT_BACKUP_AUTH_RESET)) != 0U &&
        p->jt808_auth_reset != NULL) {
        uint8_t channel_mask = 0U;
        if ((effects & F39_EFFECT_MAIN_AUTH_RESET) != 0U)
            channel_mask |= F39_AUTH_CHANNEL_MAIN;
        if ((effects & F39_EFFECT_BACKUP_AUTH_RESET) != 0U)
            channel_mask |= F39_AUTH_CHANNEL_BACKUP;
        p->jt808_auth_reset(channel_mask, p->context);
    }
    if ((effects & F39_EFFECT_NETWORK_RECONNECT) != 0U && p->network_reconnect != NULL) {
        p->network_reconnect(p->context);
    }
    if ((effects & F39_EFFECT_MODEM_PDP_RESTART) != 0U &&
        p->modem_pdp_restart != NULL) {
        p->modem_pdp_restart(p->context);
    }
    if ((effects & F39_EFFECT_GNSS_REFRESH) != 0U && p->gnss_set_mode != NULL &&
        p->config != NULL) {
        p->gnss_set_mode(p->config->gnss_type, p->config->gpsbds_mode, p->context);
    }
    if ((effects & F39_EFFECT_JT808_REREGISTER) != 0U && p->jt808_reregister != NULL) {
        p->jt808_reregister(p->context);
    }
    if ((effects & F39_EFFECT_REMAINING_REFRESH) != 0U && p->remaining_refresh != NULL) {
        p->remaining_refresh(p->context);
    }
    if ((effects & F39_EFFECT_FOTA_RECHECK) != 0U && p->fota_recheck != NULL) {
        p->fota_recheck(p->context);
    }
}

static bool config_string(const char *s, uint16_t capacity)
{
    uint16_t i;
    if (s == NULL || capacity == 0U) return false;
    for (i = 0U; i < capacity; ++i) if (s[i] == '\0') return true;
    return false;
}

static bool external_text(const char *s, uint16_t length, uint16_t maximum)
{
    return length <= maximum && (length == 0U || s != NULL);
}

static bool valid_config_text(const device_config_t *c)
{
    return config_string(c->terminal_model, CFG_MODEL_LEN) &&
           config_string(c->pid, CFG_PID_LEN) &&
           config_string(c->server_ip, CFG_IP_LEN) &&
           config_string(c->backup_ip, CFG_IP_LEN) &&
           config_string(c->apn, CFG_APN_LEN) &&
           config_string(c->plate_no, CFG_PLATE_LEN) &&
           config_string(c->device_api_key, CFG_DEVICE_API_KEY_LEN);
}

static bool device_id(const device_config_t *c, const f39_platform_t *p,
                      char terminal_id[8])
{
    char imei[F39_IMEI_MAX_LENGTH + 1U];
    if (!external_text(p->imei, p->imei_len, F39_IMEI_MAX_LENGTH)) return false;
    if (p->imei_len > 0U) (void)memcpy(imei, p->imei, p->imei_len);
    imei[p->imei_len] = '\0';
    return terminal_id_derive(c->pid, imei, terminal_id);
}

static bool effects_ready(uint32_t effects, const f39_platform_t *p)
{
    if ((effects & F39_EFFECT_TIMER_REFRESH) != 0U && p->timer_refresh == NULL) return false;
    if ((effects & F39_EFFECT_NETWORK_RECONNECT) != 0U && p->network_reconnect == NULL) return false;
    if ((effects & (F39_EFFECT_MAIN_AUTH_RESET |
                    F39_EFFECT_BACKUP_AUTH_RESET)) != 0U &&
        p->jt808_auth_reset == NULL) return false;
    if ((effects & F39_EFFECT_MODEM_PDP_RESTART) != 0U && p->modem_pdp_restart == NULL) return false;
    if ((effects & F39_EFFECT_GNSS_REFRESH) != 0U && p->gnss_set_mode == NULL) return false;
    if ((effects & F39_EFFECT_JT808_REREGISTER) != 0U && p->jt808_reregister == NULL) return false;
    if ((effects & F39_EFFECT_REMAINING_REFRESH) != 0U && p->remaining_refresh == NULL) return false;
    if ((effects & F39_EFFECT_FOTA_RECHECK) != 0U && p->fota_recheck == NULL) return false;
    return true;
}

static f39_result_t query(const f39_request_t *r, f39_platform_t *p,
                          f39_reply_t *out)
{
    const device_config_t *c = p->config;
    const char *name;
    char terminal_id[8];
    if (!operation_name(r->operation, &name) || c == NULL || !valid_config_text(c)) {
        return F39_RESULT_INVALID;
    }
    switch (r->operation) {
    case F39_OPERATION_PARAM:
        reply_clear(out);
        /* Terminal command spec sheet1 row 3: bracketed field format,
         * including the SIM ICCID.  FIP[] stays empty when no backup platform
         * is configured rather than being omitted, so the field set is fixed. */
        if (!external_text(p->version, p->version_len, F39_VERSION_MAX_LENGTH) ||
            !external_text(p->imei, p->imei_len, F39_IMEI_MAX_LENGTH) ||
            !external_text(p->iccid, p->iccid_len, F39_ICCID_MAX_LENGTH) ||
            !device_id(c, p, terminal_id) ||
            !reply_append(out,
                          "PRO[JT808_2013]VER[%.*s]IMEI[%.*s]ICCID[%.*s]"
                          "PID[%.*s]CSQ[%d]GPS[%u]",
                          (int)p->version_len, p->version != NULL ? p->version : "",
                          (int)p->imei_len, p->imei != NULL ? p->imei : "",
                          (int)p->iccid_len, p->iccid != NULL ? p->iccid : "",
                          (int)(CFG_PID_LEN - 1), c->pid,
                          p->csq, (unsigned)p->gps_satellites)) {
            return failure(out, name, "reply-too-long");
        }
        if (c->backup_ip[0] != '\0') {
            if (!reply_append(out, "IP[%.*s:%u]FIP[%.*s:%u]",
                              (int)CFG_IP_LEN, c->server_ip, (unsigned)c->server_port,
                              (int)CFG_IP_LEN, c->backup_ip, (unsigned)c->backup_port)) {
                return failure(out, name, "reply-too-long");
            }
        } else if (!reply_append(out, "IP[%.*s:%u]FIP[]",
                                 (int)CFG_IP_LEN, c->server_ip,
                                 (unsigned)c->server_port)) {
            return failure(out, name, "reply-too-long");
        }
        /* The APN user and password fields are deliberately left empty, as in
         * the spec's own APN[CMIOT,,] example: this reply goes out over SMS in
         * cleartext, and echoing stored credentials there would leak them. */
        if (!reply_append(out, "FORCE[%u:%u]ACC[%u]APN[%.*s,,]\r\n",
                          (unsigned)c->report_moving_s,
                          (unsigned)c->report_stopped_s,
                          p->acc_on ? 1U : 0U,
                          (int)CFG_APN_LEN, c->apn)) {
            return failure(out, name, "reply-too-long");
        }
        return F39_RESULT_OK;
    case F39_OPERATION_PID:
        reply_clear(out);
        {
            /* Terminal command spec sheet1: PID# echoes the full 11-digit
             * device ID, not the 7-byte JT808 terminal id derived from it. */
            char pid_text[CFG_PID_LEN];
            if (!device_id(c, p, terminal_id)) return failure(out,name,"identity");
            if (c->pid[0] != '\0') {
                (void)memcpy(pid_text, c->pid, CFG_PID_LEN - 1U);
                pid_text[CFG_PID_LEN - 1U] = '\0';
            } else {
                char imei[F39_IMEI_MAX_LENGTH + 1U];
                if (p->imei_len != 15U) return failure(out,name,"identity");
                (void)memcpy(imei, p->imei, 15U);
                imei[15] = '\0';
                (void)memcpy(pid_text, imei + 4U, 11U);
                pid_text[11] = '\0';
            }
            return reply_append(out, "PID,%s=Success!\r\n", pid_text) ?
            F39_RESULT_OK : failure(out, name, "reply-too-long");
        }
    case F39_OPERATION_IP:
        reply_clear(out);
        return reply_append(out, "IP,%.*s,%u=Success!\r\n", (int)CFG_IP_LEN, c->server_ip,
                            (unsigned)c->server_port) ? F39_RESULT_OK :
            failure(out, name, "reply-too-long");
    case F39_OPERATION_FIP:
        reply_clear(out);
        if (c->backup_ip[0] != '\0') {
            return reply_append(out, "FIP,%.*s,%u=Success!\r\n", (int)CFG_IP_LEN, c->backup_ip,
                                (unsigned)c->backup_port) ? F39_RESULT_OK :
                failure(out, name, "reply-too-long");
        }
        return reply_append(out, "FIP,0=Success!\r\n") ? F39_RESULT_OK :
            failure(out, name, "reply-too-long");
    case F39_OPERATION_FREQ:
        reply_clear(out);
        return reply_append(out, "FREQ,%u,%u=Success!\r\n", (unsigned)c->report_moving_s,
                            (unsigned)c->report_stopped_s) ? F39_RESULT_OK : failure(out,name,"reply-too-long");
    case F39_OPERATION_HBT:
        reply_clear(out); return reply_append(out,"HBT,%u=Success!\r\n",(unsigned)c->heartbeat_s)?F39_RESULT_OK:failure(out,name,"reply-too-long");
    case F39_OPERATION_FKEY:
        reply_clear(out);
        return reply_append(out, "FKEY,CONFIGURED=%u\r\n",
                            c->device_api_key[0] == '\0' ? 0U : 1U) ?
               F39_RESULT_OK : failure(out, name, "reply-too-long");
    case F39_OPERATION_FOTA:
        reply_clear(out); return reply_append(out, "FOTA,STATUS=IDLE\r\n") ? F39_RESULT_OK : failure(out, name, "reply-too-long");
    case F39_OPERATION_LOG:
        reply_clear(out); return reply_append(out, "LOG,STATUS=READY\r\n") ? F39_RESULT_OK : failure(out, name, "reply-too-long");
    case F39_OPERATION_MODEL:
        reply_clear(out); return reply_append(out,"MODEL,%.*s=Success!\r\n",(int)CFG_MODEL_LEN,c->terminal_model)?F39_RESULT_OK:failure(out,name,"reply-too-long");
    case F39_OPERATION_SPEED:
        reply_clear(out); return reply_append(out,"SPEED,%u=Success!\r\n",(unsigned)c->speed_limit_kmh)?F39_RESULT_OK:failure(out,name,"reply-too-long");
    case F39_OPERATION_APN:
        reply_clear(out); return c->autoapn_en ? (reply_append(out,"APN,AUTO=Success!\r\n")?F39_RESULT_OK:failure(out,name,"reply-too-long")) : (reply_append(out,"APN,%.*s=Success!\r\n",(int)CFG_APN_LEN,c->apn)?F39_RESULT_OK:failure(out,name,"reply-too-long"));
    case F39_OPERATION_GPSDUP:
        reply_clear(out); return reply_append(out,"GPSDUP,%u=Success!\r\n",c->sleep_report_mode?0U:1U)?F39_RESULT_OK:failure(out,name,"reply-too-long");
    case F39_OPERATION_MLG:
        reply_clear(out); return reply_append(out,"MLG,%lu=Success!\r\n",(unsigned long)(c->mileage_m/100U))?F39_RESULT_OK:failure(out,name,"reply-too-long");
    case F39_OPERATION_CAR:
        reply_clear(out); return reply_append(out,"CAR,%.*s=Success!\r\n",(int)CFG_PLATE_LEN,c->plate_no)?F39_RESULT_OK:failure(out,name,"reply-too-long");
    case F39_OPERATION_GPSBDS:
        reply_clear(out); return reply_append(out,"GPSBDS,%u=Success!\r\n",(unsigned)c->gpsbds_mode)?F39_RESULT_OK:failure(out,name,"reply-too-long");
    case F39_OPERATION_GMTSET:
        reply_clear(out); return reply_append(out,"GMTSET,%c%02u%02u=Success!\r\n",c->gmt_sign<0?'W':'E',(unsigned)c->gmt_hour,(unsigned)c->gmt_min)?F39_RESULT_OK:failure(out,name,"reply-too-long");
    case F39_OPERATION_VIBSENS:
        reply_clear(out); return reply_append(out,"VIBSENS,%u=Success!\r\n",(unsigned)c->vib_sens)?F39_RESULT_OK:failure(out,name,"reply-too-long");
    default: return F39_RESULT_INVALID;
    }
}

f39_result_t f39_execute(const f39_request_t *request,
                         f39_platform_t *platform,
                         f39_reply_t *reply)
{
    const char *name;
    f39_transaction_t tx;
    char value[32];
    if (reply == NULL) return F39_RESULT_INVALID;
    reply_clear(reply);
    if (request == NULL || platform == NULL || !operation_name(request->operation, &name)) {
        return failure(reply, "F39", "invalid");
    }
    if (request->operation == F39_OPERATION_PARAM ||
        (request->argc == 0U && request->operation != F39_OPERATION_RESET &&
         request->operation != F39_OPERATION_DUALSET && request->operation != F39_OPERATION_RELAY)) {
        return query(request, platform, reply);
    }
    if (request->operation == F39_OPERATION_RESET) {
        if (request->argc != 0U) return failure(reply,name,"invalid");
        if (success(reply,name) != F39_RESULT_OK) return F39_RESULT_INVALID;
        reply->reset_pending = true;
        reply->reset_delay_ms = F39_RESET_DELAY_MS;
        return F39_RESULT_OK;
    }
    if (request->operation == F39_OPERATION_RELAY) {
        bool cut;
        float current_speed;
        if (request->argc == 0U) {
            bool state = platform->relay_get != NULL && platform->relay_get(platform->context);
            reply_clear(reply);
            return reply_append(reply,"RELAY,%u=Success!\r\n",state?1U:0U)?F39_RESULT_OK:failure(reply,name,"reply-too-long");
        }
        if (request->argc != 1U ||
            !arg_text(request,0U,value,sizeof(value)) || platform->relay_set == NULL ||
            (strcmp(value,"0") != 0 && strcmp(value,"1") != 0)) return failure(reply,name,"invalid");
        cut = (value[0] == '1');
        if (cut) {
            if (platform->gps_valid == NULL || !platform->gps_valid(platform->context) ||
                platform->gps_speed_kmh == NULL) return failure(reply,name,"unsafe");
            current_speed = platform->gps_speed_kmh(platform->context);
            if (!isfinite(current_speed) || current_speed < 0.0f || current_speed >= 20.0f) {
                return failure(reply,name,"unsafe");
            }
        }
        if (!platform->relay_set(cut, platform->context)) return failure(reply,name,"busy");
        reply_clear(reply);
        return reply_append(reply,"RELAY,%u=Success!\r\n",cut?1U:0U)?F39_RESULT_OK:failure(reply,name,"reply-too-long");
    }
    if (platform->config == NULL || platform->persist == NULL) return failure(reply,name,"invalid");
    f39_transaction_init(&tx, platform->config, platform->persist, platform->context);
    if (!f39_prepare_config(request, platform->config, &tx)) {
        return failure(reply,name,"config");
    }
    if (!effects_ready(tx.effects, platform) ||
        ((tx.effects & F39_EFFECT_GNSS_REFRESH) != 0U &&
        (platform->gnss_set_mode == NULL ||
         (tx.candidate.gnss_type != GNSS_TYPE_TAU804M)))) {
        return failure(reply,name,"unsupported-receiver");
    }
    if (f39_commit_config(&tx) != F39_RESULT_OK) {
        return failure(reply,name,"config");
    }
    apply_effects(tx.effects, platform);
    if (request->operation == F39_OPERATION_FKEY) {
        return query(request, platform, reply);
    }
    return success(reply,name);
}
