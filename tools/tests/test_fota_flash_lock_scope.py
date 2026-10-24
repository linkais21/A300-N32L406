"""OTA must not hold the external-flash owner while it waits on the network.

Regression for: OTA locked EXT_FLASH_OWNER_OTA from the update check through
the whole download, so blind-zone appends and parameter saves failed with
BUSY/LOCK_FAILED whenever OTA was retrying against an unreachable server.
"""
from test_fota_platform_flow import HARNESS, run_flow

CASES = r'''
static bool other_owner_can_lock(void){
    if(flash_owner)return false;
    flash_owner=EXT_FLASH_OWNER_BLIND_ZONE;flash_owner=0;return true;
}
int main(void){
    /* Check phase: TCP opening and waiting for the HTTP response. */
    fresh();pump(2);assert(opens==1 && workspace_owner==SERVICE_WORKSPACE_OWNER_OTA);
    assert(other_owner_can_lock());
    tcp=TCP_STATE_OPEN;pump(1);assert(sends==1 && other_owner_can_lock());

    /* Unreachable server: every retry and the 60 s back-off leave flash free. */
    fresh();
    for(unsigned i=0;i<220 && fota_get_state()!=FOTA_STATE_ERROR;i++){
        pump(1);assert(other_owner_can_lock());
        if(fota_get_state()!=FOTA_STATE_ERROR)g_tick_ms+=1000;
    }
    assert(fota_get_state()==FOTA_STATE_ERROR && opens==3 && !flash_owner);

    /* Download phase: erase, connect and receive between chunks keep flash free. */
    fresh();connect_check();
    update(FW_VERSION_COUNTER+1,4300,"http://fota.lhhn.net/api/device/updates/tasks/17/download?token=task-token-123");
    assert(other_owner_can_lock());
    download_open();assert(other_owner_can_lock());

    /* A foreign owner mid-operation defers OTA flash work instead of failing it. */
    fresh();connect_check();
    update(FW_VERSION_COUNTER+1,4300,"http://fota.lhhn.net/api/device/updates/tasks/17/download?token=task-token-123");
    unsigned before=erases;flash_owner=EXT_FLASH_OWNER_CONFIG;pump(3);
    assert(erases==before && fota_get_state()!=FOTA_STATE_ERROR);
    flash_owner=0;download_open();assert(erases>before && !flash_owner);
    return 0;
}
'''

if __name__ == "__main__":
    run_flow(HARNESS + CASES, "flash_lock_scope")
    print("test_fota_flash_lock_scope: PASS")
