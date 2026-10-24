"""If-Range mismatch must restart durably, without accepting mixed content."""
from test_fota_platform_flow import HARNESS, run_flow


def main():
    run_flow(HARNESS + r'''
static void start_download(void){
    unsigned before=sends;
    for(unsigned i=0;i<160 && sends==before;i++){
        if(tcp==TCP_STATE_OPENING)tcp=TCP_STATE_OPEN;
        pump(1);g_tick_ms+=100;
    }
    assert(sends==before+1 && fota_get_state()==FOTA_STATE_DOWNLOADING);
}
int main(void){
    fota_checkpoint_t c,loaded;uint8_t hash[32]={0},sig[64]={0};
    const char *url="http://fota.lhhn.net/fw";
    fota_request_t req={"http://fota.lhhn.net/fw?token=task-token-123",8193,NULL,FW_VERSION_COUNTER+1,hash,sig,1};
    for(unsigned partial=0;partial<2;partial++){
        fresh();memset(&c,0,sizeof c);strcpy(c.url,url);strcpy(c.etag,"old");
        c.expected_length=8193;c.version=req.version;c.offset=4096;c.running_crc=123;
        flash_owner=EXT_FLASH_OWNER_OTA;assert(fota_checkpoint_commit(&c));flash_owner=0;
        memset(flash+0x10000,0x5a,4096);
        assert(fota_start_request(&req)==0);start_download();
        assert(strstr(request,"Range: bytes=4096-\r\nIf-Range: old\r\n"));
        fota_on_http_header(partial?
            "HTTP/1.1 206 Partial Content\r\nContent-Length: 4097\r\nContent-Range: bytes 4096-8192/8193\r\nETag: new\r\n\r\n":
            "HTTP/1.1 200 OK\r\nContent-Length: 8193\r\nETag: new\r\n\r\n");
        uint8_t byte=0x12;fota_on_chunk(&byte,1U,4096U);pump(1);
        assert(!resets && flash[0x10000]==0x5a);
        if(partial){assert(fota_get_state()==FOTA_STATE_ERROR);continue;}
        assert(fota_get_state()==FOTA_STATE_PREPARING);
        assert(fota_checkpoint_load(url,8193,&loaded));
        assert(loaded.offset==0U && loaded.running_crc==0xffffffffU && !strcmp(loaded.etag,"new"));
        /* Reset after zero commit, before old prefix erase. */
        fota_cancel();fota_init();assert(fota_start_request(&req)==0);start_download();
        assert(!strstr(request,"Range:") && fota_get_progress()==0);
        for(unsigned i=0;i<12288;i++)assert(flash[0x10000+i]==0xff);
        fota_cancel();assert(!flash_owner && !workspace_owner);
    }
    puts("If-Range: changed ETag 200 durably restarts; changed ETag 206 rejected PASS");return 0;
}
''', "if_range_restart")


if __name__ == "__main__":
    main()
