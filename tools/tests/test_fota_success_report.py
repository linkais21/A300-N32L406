"""Run reboot-success reporting against production C and the NOR/modem harness."""
from test_fota_platform_flow import HARNESS, run_flow


def main():
    run_flow(HARNESS + r'''
static void seed_report(uint8_t state, uint32_t version) {
    fota_checkpoint_t c={0};
    seed_bcr(state);
    bcr_record_t *b=(bcr_record_t *)(flash+BCR_SLOT_A_ADDR);
    b->image_version=version;b->transaction_length=4268;
    b->crc32=crc32_compute(b,offsetof(bcr_record_t,crc32));
    c.version=version;c.expected_length=4300;c.offset=4096;
    strcpy(c.url,"http://fota.lhhn.net/d/task-token-123?d=12345678901");
    flash_owner=EXT_FLASH_OWNER_OTA;assert(fota_checkpoint_commit(&c));flash_owner=0;
}
static void report_open(void) {
    pump(2);assert(opens==1);tcp=TCP_STATE_OPEN;pump(1);
    assert(strstr(request,"POST /api/device/updates/progress HTTP/1.1"));
    assert(strstr(request,"\"state\":\"success\""));
    assert(strstr(request,"\"bytesReceived\":4300"));
    assert(strstr(request,"X-OTA-Token: task-token-123"));
}
static void reply(unsigned code) {
    char h[100];snprintf(h,sizeof h,"HTTP/1.1 %u Result\r\nContent-Length: 0\r\n\r\n",code);
    bytes(h,strlen(h));pump(1);
}
static void replace_url(const char *url) {
    fota_checkpoint_t c;flash_owner=EXT_FLASH_OWNER_OTA;
    assert(fota_checkpoint_read(&c)==1);strcpy(c.url,url);
    assert(fota_checkpoint_commit(&c));flash_owner=0;
}
int main(void) {
    fresh();seed_report(BCR_TRIAL,FW_VERSION_COUNTER);g_tick_ms=29999;
    fota_confirm_trial_process();assert(!resets && !opens);
    g_tick_ms=30000;bcr_read_verified=true;
    ready=false;fota_confirm_trial_process();assert(!resets);
    ready=true;online=false;fota_confirm_trial_process();assert(!resets);
    online=true;fota_confirm_trial_process();assert(resets==1);
    fota_init();resets=0;report_open();reply(201);
    fresh();seed_report(BCR_TRIAL,FW_VERSION_COUNTER+1);g_tick_ms=30000;
    fota_confirm_trial_process();assert(!resets && !opens);
    fresh();seed_report(BCR_ACTIVE,FW_VERSION_COUNTER);report_open();reply(201);
    assert(!resets && !workspace_owner && !flash_owner);
    fota_init();opens=sends=0;request[0]=0;connect_check();
    assert(strstr(request,"GET /api/device/updates/check"));
    /* A lost response preserves the durable report across reset. */
    fresh();seed_report(BCR_ACTIVE,FW_VERSION_COUNTER);report_open();reply(500);
    g_tick_ms+=15000;pump(1);assert(!resets && !workspace_owner && !flash_owner);
    fota_init();opens=sends=0;report_open();reply(201);
    /* Failed tombstone remains retryable and never resets a running app. */
    fresh();seed_report(BCR_ACTIVE,FW_VERSION_COUNTER);report_open();fail_write=true;reply(201);
    assert(!resets && !workspace_owner && !flash_owner);
    fail_write=false;fota_init();opens=sends=0;report_open();reply(201);
    for(unsigned i=0;i<3;i++) {
        fresh();seed_report(i==0?BCR_TRIAL:i==1?BCR_ROLLBACK:BCR_ACTIVE,
                           i==2?FW_VERSION_COUNTER+1:FW_VERSION_COUNTER);
        pump(2);if(tcp==TCP_STATE_OPENING){tcp=TCP_STATE_OPEN;pump(1);}
        assert(!strstr(request,"\"state\":\"success\""));
    }
    fresh();seed_report(BCR_ACTIVE,FW_VERSION_COUNTER);ready=false;pump(5);assert(!opens);
    ready=true;workspace_owner=SERVICE_WORKSPACE_OWNER_DIAGNOSTIC;pump(2);assert(!opens);
    workspace_owner=0;report_open();reply(201);
    /* Query-token packages and non-default HTTP authority survive reboot. */
    fresh();seed_report(BCR_ACTIVE,FW_VERSION_COUNTER);
    strcpy(cfg.fota_url,"http://fota.lhhn.net:8088");
    replace_url("http://fota.lhhn.net:8088/fw?token=task-token-123");
    report_open();assert(strstr(request,"Host: fota.lhhn.net:8088\r\n"));reply(201);
    /* A fragmented ACK is not accepted until the complete header arrives. */
    fresh();seed_report(BCR_ACTIVE,FW_VERSION_COUNTER);report_open();
    bytes("HTTP/1.1 201 Created\r\n",22);pump(1);assert(workspace_owner);
    bytes("Content-Length: 0\r\n\r\n",21);pump(1);assert(!workspace_owner && !resets);
    /* 401/500/disconnect/silence cannot monopolize OTA scheduling forever. */
    for(unsigned failure=0;failure<4;failure++) {
        fresh();seed_report(BCR_ACTIVE,FW_VERSION_COUNTER);
        for(unsigned attempt=0;attempt<3;attempt++) {
            unsigned opened=opens;pump(2);assert(opens==opened+1);
            tcp=TCP_STATE_OPEN;pump(1);assert(strstr(request,"\"state\":\"success\""));
            if(failure<2)reply(failure?500:401);
            else if(failure==2){tcp=TCP_STATE_CLOSED;pump(1);}
            g_tick_ms+=15000;pump(1);
            assert(!workspace_owner && !flash_owner && !resets);
            g_tick_ms+=59999;pump(1);assert(opens==opened+1);
            g_tick_ms++;
        }
        pump(2);tcp=TCP_STATE_OPEN;pump(1);
        assert(strstr(request,"GET /api/device/updates/check"));no_update();
        /* The next six-hour check cycle renews the bounded report budget. */
        g_tick_ms+=21600000U;pump(2);tcp=TCP_STATE_OPEN;pump(1);
        assert(strstr(request,"\"state\":\"success\""));reply(201);
    }
    /* Reject foreign hosts, malformed/empty tokens and damaged records. */
    const char *bad[]={"http://foreign.invalid/d/task-token-123",
        "http://fota.lhhn.net/d/", "http://fota.lhhn.net/d/bad/token",
        "http://fota.lhhn.net/fw?token=", "http://fota.lhhn.net/fw?x=/d/task-token-123"};
    for(unsigned i=0;i<sizeof bad/sizeof bad[0];i++) {
        fresh();seed_report(BCR_ACTIVE,FW_VERSION_COUNTER);replace_url(bad[i]);
        connect_check();assert(strstr(request,"GET /api/device/updates/check"));
    }
    fresh();seed_report(BCR_ACTIVE,FW_VERSION_COUNTER);
    fail_read_at=FOTA_CHECKPOINT_SLOT_A;pump(3);assert(!opens && !workspace_owner && !flash_owner);
    fail_read_at=0;g_tick_ms+=60000;report_open();reply(201);
    fresh();seed_report(BCR_ACTIVE,FW_VERSION_COUNTER);
    flash[FOTA_CHECKPOINT_SLOT_A+20]^=1;connect_check();
    assert(strstr(request,"GET /api/device/updates/check"));
    fresh();seed_report(BCR_ACTIVE,FW_VERSION_COUNTER);inline_status_response=true;
    report_open();pump(1);assert(!workspace_owner && !resets);
    fresh();seed_report(BCR_ACTIVE,FW_VERSION_COUNTER);report_open();
    const char *malformed="HTTP/1.1 201X Invalid\r\nContent-Length: 0\r\n\r\n";
    bytes(malformed,strlen(malformed));pump(1);g_tick_ms+=15000;pump(1);
    fota_init();opens=sends=0;report_open();reply(201);
    fresh();seed_report(BCR_ACTIVE,FW_VERSION_COUNTER);g_tick_ms=0xfffffff0U;
    report_open();g_tick_ms+=15000;pump(1);assert(!workspace_owner && !resets);
    g_tick_ms+=60000;pump(2);tcp=TCP_STATE_OPEN;pump(1);reply(201);
    assert(!strstr(logs,"task-token-123"));
    puts("success report: ACTIVE/version gate, reboot recovery, ACK cleanup and failure preservation PASS");
    return 0;
}
''', 'success_report')


if __name__ == '__main__':
    main()
