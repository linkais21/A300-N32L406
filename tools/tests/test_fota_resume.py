"""Production FOTA and journal with one-way NOR and asynchronous modem replay."""
from test_fota_platform_flow import HARNESS, run_flow


def test_resume_cleanup_and_boundary_checkpoint():
    run_flow(HARNESS + r'''
static void start_download(void){
    unsigned previous=sends;
    for(unsigned i=0;i<160 && sends==previous;i++){
        if(tcp==TCP_STATE_OPENING)tcp=TCP_STATE_OPEN;
        pump(1);g_tick_ms+=100;
    }
    assert(sends==previous+1);assert_no_device_key();
}
int main(void){
    fota_checkpoint_t c,loaded;fota_status_t status;
    uint8_t package_sha256[32]={0},signature[64]={0};
    const char *checkpoint_url="http://fota.lhhn.net/a.bin";
    fota_request_t req={"http://fota.lhhn.net/a.bin?token=task-token-123",13000,"v7",3002,
                        package_sha256,signature,1U};
    uint8_t data[5000];unsigned before;bool token_in_flash=false;
    fresh();memset(&c,0,sizeof c);strcpy(c.url,checkpoint_url);strcpy(c.etag,req.etag);
    c.expected_length=13000;c.version=3002;c.offset=4096;c.running_crc=0;
    flash_owner=EXT_FLASH_OWNER_OTA;assert(fota_checkpoint_commit(&c));flash_owner=0;
    memset(flash+0x10000,0x5a,4096);memset(flash+0x11000,0,12288);memset(flash+0x14000,0x36,4096);erases=0;
    req.expected_length=0;assert(fota_start_request(&req)<0);req.expected_length=13000;
    assert(fota_start_request(&req)==0 && !sends);
    fota_get_status(&status);assert(status.offset==4096 && status.crc32==0xffffffffU);
    assert(!strcmp(status.url,checkpoint_url) && !strstr(status.url,"token="));
    assert(!strcmp(status.etag,"v7") && status.expected_length==13000);
    start_download();assert(erases==3 && opens==1 && sends==1);
    assert(erased[0]==0x11000 && erased[1]==0x12000 && erased[2]==0x13000);
    assert(strstr(request,"Range: bytes=4096-\r\nIf-Range: v7\r\n"));
    for(unsigned i=0;i<4096;i++){assert(flash[0x10000+i]==0x5a);assert(flash[0x14000+i]==0x36);}
    for(unsigned i=0;i<12288;i++)assert(flash[0x11000+i]==255);
    fota_on_http_header("HTTP/1.1 206 Partial Content\r\nContent-Length: 8904\r\nContent-Range: bytes 4096-12999/13000\r\nETag: v7\r\n\r\n");
    memset(data,0xa5,sizeof data);fota_on_chunk(data,5000,4096);
    assert(fota_checkpoint_load(checkpoint_url,13000,&loaded) && loaded.offset==8192);
    for(size_t i=0;i+14<=sizeof flash;i++)if(!memcmp(flash+i,"task-token-123",14))token_in_flash=true;
    assert(!strstr(loaded.url,"token=") && !token_in_flash);
    assert(loaded.running_crc==crc32_update(0,data,4096));
    assert(loaded.version==3002 && !strcmp(loaded.etag,"v7"));
    fota_on_chunk(data,5000,4096);assert(fota_get_progress()==9096);
    fota_cancel();erases=0;assert(fota_start_request(&req)==0);start_download();
    assert(erases==2 && erased[0]==0x12000 && erased[1]==0x13000);
    assert(strstr(request,"Range: bytes=8192-"));
    /* 200 reset is journaled on its own process step, before any prefix erase. */
    erases=0;before=closes;
    fota_on_http_header("HTTP/1.1 200 OK\r\nContent-Length: 13000\r\nETag: v7\r\n\r\n");
    fota_on_chunk(data,1,0);assert(fota_get_progress()==8192);
    pump(1);assert(closes==before+1 && erases==1 && erased[0]>=0x102000);
    assert(fota_checkpoint_load(checkpoint_url,13000,&loaded) && loaded.offset==0);
    assert(flash[0x10000]==0x5a);
    /* Simulate reboot while previously committed prefix has only begun cleanup. */
    pump(1);assert(flash[0x10000]==255 && flash[0x11000]==0xa5);
    fota_cancel();fota_init();erases=0;
    assert(fota_start_request(&req)==0 && fota_get_progress()==0);start_download();
    assert(erases==4 && erased[0]==0x10000 && erased[3]==0x13000);
    assert(!strstr(request,"Range:") && flash[0x14000]==0x36);
    fota_cancel();req.expected_length=14000;erases=0;
    assert(fota_start_request(&req)==0);start_download();
    assert(fota_get_progress()==0 && erases==5 && erased[1]==0x10000);
    fota_on_http_header("HTTP/1.1 206 Partial Content\r\nContent-Length: 14000\r\nContent-Range: bytes 0-13999/16000\r\n\r\n");
    pump(1);assert(fota_get_state()==FOTA_STATE_ERROR && flash[0x14000]==0x36);
    fota_cancel();
    puts("resume: bounded cleanup/boundary CRC/duplicate/identity/unknown size/200 durable reset/reboot during prefix erase PASS");return 0;
}
''', "resume")


if __name__ == "__main__":
    test_resume_cleanup_and_boundary_checkpoint()
    print("test_fota_resume: PASS")
