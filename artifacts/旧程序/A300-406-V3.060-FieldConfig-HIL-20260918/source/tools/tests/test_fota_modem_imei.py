"""Real OTA request keeps protocol fields and adds optional modem asset identity."""
from test_fota_platform_flow import HARNESS, run_flow

CASES = r'''
int main(void) {
    fresh();connect_check();
    assert(strstr(request,"\r\nX-Modem-IMEI: 860123456789012\r\n"));
    assert(strstr(request,"deviceId=12345678901&deviceModel=A300-406&"));
    assert(!strstr(logs,"860123456789012"));
    no_update();
    const char *invalid[]={"","123","8601234567890123","86012345678901X","8601234567890\r\n"};
    for(unsigned i=0;i<sizeof invalid/sizeof invalid[0];i++) {
        fresh();modem_imei=invalid[i];connect_check();
        assert(!strstr(request,"X-Modem-IMEI:"));no_update();
    }
    fresh();modem_imei="860123456789012";connect_check();
    update(FW_VERSION_COUNTER+1,4300,"http://fota.lhhn.net/d/task-token-123?d=12345678901");
    download_open();assert(!strstr(request,"X-Modem-IMEI:"));
    assert(strstr(request,"GET /d/task-token-123?d=12345678901 HTTP/1.1\r\n"));
    return 0;
}
'''

if __name__ == '__main__':
    run_flow(HARNESS + CASES, 'modem_imei')
    print('test_fota_modem_imei: PASS')
