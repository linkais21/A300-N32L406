"""Actual command commit -> transport ACK -> disruptive runtime effects."""
import test_at_config_serial_f39 as base

MAIN = r'''
static unsigned acknowledged, runtime_effects;
static bool expected_success;
static void ack(bool success, void *context) {
    (void)context;assert(success==expected_success);assert(runtime_effects==0);
    ++acknowledged;
}
static void effect(void *context) {
    (void)context;assert(acknowledged==1);++runtime_effects;
}
static void auth(uint8_t mask,void *context) { assert(mask);effect(context); }
static bool persist(const device_config_t *candidate,void *context) {
    (void)context;assert(!acknowledged);return cfg_store_candidate(candidate);
}
static int send_stub(const char *to,const char *text,void *context) {
    (void)to;(void)text;(void)context;return 0;
}
static void reset_stub(uint32_t delay,void *context) {(void)delay;effect(context);}
int main(void) {
    const char *commands[]={"PID,12345678901","FIP,backup.example,7018","APN,cmiot,,","RESET"};
    f39_platform_t p={0};p.config=&config;p.persist=persist;
    p.network_reconnect=effect;p.modem_pdp_restart=effect;
    p.jt808_reregister=effect;p.jt808_auth_reset=auth;p.remaining_refresh=effect;
    config.gnss_type=GNSS_TYPE_TAU804M;
    at_config_bind_f39(&p,send_stub,reset_stub,NULL);
    for(unsigned i=0;i<4;i++) {
        acknowledged=runtime_effects=0;expected_success=true;
        assert(at_config_execute_text_command_ack((const uint8_t*)commands[i],strlen(commands[i]),ack,NULL));
        assert(acknowledged==1&&runtime_effects>0);
    }
    acknowledged=runtime_effects=0;expected_success=false;persist_ok=false;
    device_config_t old=config;
    const char *change="FIP,new.example,80";
    assert(!at_config_execute_text_command_ack((const uint8_t*)change,strlen(change),ack,NULL));
    assert(acknowledged==1&&!runtime_effects&&!memcmp(&old,&config,sizeof config));
    acknowledged=0;
    assert(!at_config_execute_text_command_ack((const uint8_t*)"BAD",3,ack,NULL));
    assert(acknowledged==1&&!runtime_effects);
    return 0;
}
'''

if __name__ == '__main__':
    base.HARNESS=base.HARNESS.replace('int main(void)', 'int original_main(void)')+MAIN
    raise SystemExit(base.main())
