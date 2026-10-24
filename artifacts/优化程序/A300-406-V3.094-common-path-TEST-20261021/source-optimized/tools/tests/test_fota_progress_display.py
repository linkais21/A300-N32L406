from test_fota_platform_flow import HARNESS, run_flow

def main():
    run_flow(HARNESS+r'''
int main(void){
    uint8_t data[4300];memset(data,0x5a,sizeof data);
    fresh();connect_check();update(FW_VERSION_COUNTER+1,4300,"http://fota.lhhn.net/fw?token=task-token-123");download_open();
    assert(strstr(logs,"[FOTA] prepare erase=")!=NULL);
    assert(strstr(logs,"download progress=0% bytes=0/4300")!=NULL);
    fota_on_http_header("HTTP/1.1 200 OK\r\nContent-Length: 4300\r\n\r\n");
    fota_on_chunk(data,4300,0);
    assert(strstr(logs,"download progress=100% bytes=4300/4300")!=NULL);
    assert(strstr(logs,"install progress=verify-start")!=NULL);
    return 0;
}
''','progress_display')
    print('FOTA progress display PASS')
if __name__=='__main__':main()
