from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=root/'src/f39_config_adapter.c'
s=p.read_text(encoding='utf-8')
start=s.index('static bool prepare_ip(')
end=s.index('static bool prepare_freq(',start)
s=s[:start]+'''/* Main and backup endpoints have identical commit effects; only FIP may
 * disable its endpoint with a single zero argument. */
static bool prepare_server(const f39_request_t *request,
                           device_config_t *candidate, uint32_t *effects)
{
    bool backup = request->operation == F39_OPERATION_FIP;
    char host[CFG_IP_LEN];
    uint16_t port;
    char *target = backup ? candidate->backup_ip : candidate->server_ip;
    uint16_t *target_port = backup ? &candidate->backup_port : &candidate->server_port;
    char *auth = backup ? candidate->backup_auth_code : candidate->auth_code;
    if (backup && arg_equals(request, 0U, "0")) {
        if (request->argc != 1U) return false;
        host[0] = '\\0';
        port = 0U;
    } else if (!prepare_endpoint(request, host, sizeof(host), &port)) {
        return false;
    }
    if (strcmp(target, host) != 0 || *target_port != port) {
        (void)strcpy(target, host);
        *target_port = port;
        auth[0] = '\\0';
        *effects |= backup ? F39_EFFECT_BACKUP_AUTH_RESET : F39_EFFECT_MAIN_AUTH_RESET;
    }
    *effects |= F39_EFFECT_NETWORK_RECONNECT;
    return true;
}

'''+s[end:]
s=s.replace('return prepare_ip(request, candidate, effects);','return prepare_server(request, candidate, effects);')
s=s.replace('return prepare_fip(request, candidate, effects);','return prepare_server(request, candidate, effects);')
p.write_text(s,encoding='utf-8',newline='\n')
