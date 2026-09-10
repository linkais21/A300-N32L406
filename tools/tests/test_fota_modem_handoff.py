"""Real EC800M deferred UDP events followed by the real authenticated OTA check."""
import subprocess
import tempfile
from pathlib import Path
from test_ec800m_urc_demux import HEADERS, HARNESS, compiler, ROOT


EXTRA = r'''
#include "fota.h"
#include "ext_flash_store.h"
#include "service_workspace.h"
static bool handoff_active;
static char modem_command[600],last_http[512];
static unsigned modem_command_length,payload_left,udp_opens,tcp_opens,http_requests;
static bool queued_error;
static uint8_t flash[2*1024*1024];
static ext_flash_owner_t flash_owner;
static bool task5_uart_tx(uint8_t byte){
    if(!handoff_active)return false;
    assert(modem_command_length+1U<sizeof modem_command);
    modem_command[modem_command_length++]=(char)byte;modem_command[modem_command_length]=0;
    if(payload_left){
        if(--payload_left==0){
            if(!strncmp(modem_command,"GET ",4)){++http_requests;strcpy(last_http,modem_command);}
            modem_command_length=0;host_feed_rx("\r\nSEND OK\r\n");
        }return true;
    }
    if(byte!='\n')return true;
    if(strstr(modem_command,"AT+QIOPEN=1,1,\"UDP\"")){
        ++udp_opens;host_feed_rx(queued_error?"\r\n+QIOPEN: 1,565\r\nOK\r\n":"\r\n+QIOPEN: 1,0\r\nOK\r\n");
    }else if(strstr(modem_command,"AT+QIOPEN=1,1,\"TCP\"")){
        ++tcp_opens;host_feed_rx("\r\nOK\r\n+QIOPEN: 1,0\r\n");
    }else if(sscanf(modem_command,"AT+QISEND=1,%u",&payload_left)==1){host_feed_rx(">\r\n");}
    else host_feed_rx("\r\nOK\r\n");
    modem_command_length=0;return true;
}
bool ext_flash_try_lock_now(ext_flash_owner_t owner){if(flash_owner)return false;flash_owner=owner;return true;}
bool ext_flash_try_lock(ext_flash_owner_t owner){return ext_flash_try_lock_now(owner);}
void ext_flash_unlock(ext_flash_owner_t owner){assert(flash_owner==owner);flash_owner=0;}
bool ext_flash_read(ext_flash_owner_t owner,uint32_t addr,void *out,uint32_t n){assert(flash_owner==owner && addr+n<=sizeof flash);memcpy(out,flash+addr,n);return true;}
bool ext_flash_erase(ext_flash_owner_t owner,uint32_t addr,uint32_t n){assert(flash_owner==owner && n==4096 && addr%4096==0);memset(flash+addr,255,n);return true;}
bool ext_flash_write_verified(ext_flash_owner_t owner,uint32_t addr,const void *in,uint32_t n){const uint8_t *p=in;assert(flash_owner==owner);for(uint32_t i=0;i<n;i++){assert((flash[addr+i]&p[i])==p[i]);flash[addr+i]&=p[i];}return true;}
bool terminal_identity_sync(char pid[12],char phone[13],char terminal[8]){strcpy(pid,"12345678901");strcpy(phone,"012345678901");strcpy(terminal,"5678901");return true;}
bool firmware_signature_verify(const uint8_t *h,const uint8_t *s){(void)h;(void)s;return false;}
void NVIC_SystemReset(void){assert(!"unexpected reset");}
int main(void){
    assert(original_main()==0);
    handoff_active=true;wr=0;g_tick_ms=0;memset(flash,255,sizeof flash);
    ec800m_init();ec800m_test_set_state(EC800M_STATE_READY);fota_init();
    strcpy(config.fota_url,"http://fota.lhhn.net");memset(config.device_api_key,'Q',20);config.device_api_key[20]=0;
    assert(service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_DIAGNOSTIC));
    assert(ec800m_udp_send_once("example.invalid",9000,(const uint8_t *)"abc",3)==0);
    assert(udp_opens==1 && ec800m_tcp_state(1)==TCP_STATE_CLOSED);
    service_workspace_release(SERVICE_WORKSPACE_OWNER_DIAGNOSTIC);
    ec800m_process();assert(ec800m_tcp_state(1)==TCP_STATE_CLOSED);
    /* Delayed duplicate OPEN after physical close must not resurrect it. */
    host_feed_rx("\r\n+QIOPEN: 1,0\r\n");ec800m_process();ec800m_process();
    assert(ec800m_tcp_state(1)==TCP_STATE_CLOSED);
    for(unsigned i=0;i<5 && !http_requests;i++){fota_process();ec800m_process();}
    assert(tcp_opens==1 && http_requests==1 && fota_get_state()==FOTA_STATE_CHECKING);
    assert(strstr(last_http,"GET /api/device/updates/check?deviceId=12345678901&deviceModel=A300-406&currentVersionCode=3002 HTTP/1.1\r\n"));
    assert(strstr(last_http,"X-Device-Key: "));
    assert(!strstr(diag_log,config.device_api_key));
    fota_cancel();
    /* Queue an obsolete error, then open OTA before the deferred event pump:
     * channel generations must prevent the old event closing the new socket. */
    queued_error=true;udp_opens=tcp_opens=http_requests=0;g_tick_ms=100;fota_init();
    assert(ec800m_udp_send_once("example.invalid",9000,(const uint8_t *)"abc",3)==0);
    for(unsigned i=0;i<5 && !http_requests;i++){fota_process();ec800m_process();}
    assert(tcp_opens==1 && http_requests==1 && fota_get_state()==FOTA_STATE_CHECKING);
    fota_cancel();queued_error=false;
    /* A diagnostic transaction can be alive even if its workspace was
     * yielded. Preparation must not claim its channel between phases. */
    uint8_t reply[8];assert(ec800m_udp_txn_start("example.invalid",9000,(const uint8_t *)"abc",3,reply,sizeof reply,1000)==0);
    assert(!ec800m_ota_channel_prepare());
    for(unsigned i=0;i<3;i++)ec800m_udp_txn_process();
    assert(ec800m_udp_txn_result()>=0);assert(ec800m_ota_channel_prepare());
    /* Abandoned OPEN state is reconciled only after all owners are idle. */
    ec800m_test_set_tcp_open(1);assert(ec800m_ota_channel_prepare());
    assert(ec800m_tcp_state(1)==TCP_STATE_CLOSED);
    puts("test_fota_modem_handoff: real diagnostic UDP retirement and authenticated OTA admission PASS");return 0;
}
'''


def test_modem_handoff():
    cc = compiler()
    assert cc, "host compiler required"
    source = HARNESS.replace("int main(void)", "int original_main(void)")
    source = source.replace("void host_uart_tx(uint8_t byte)\n{", "static bool task5_uart_tx(uint8_t byte);\nvoid host_uart_tx(uint8_t byte)\n{\n    if(task5_uart_tx(byte))return;")
    with tempfile.TemporaryDirectory(prefix="fota_modem_") as directory:
        temp = Path(directory)
        for name, content in HEADERS.items():
            if name == "n32l40x.h":
                content += "\nvoid NVIC_SystemReset(void);\n"
            (temp / name).write_text(content, encoding="ascii")
        (temp / "harness.c").write_text(source + EXTRA, encoding="ascii")
        sources = ["ec800m.c", "ec800m_at_response.c", "sms_ingress.c", "sms_command.c",
                   "fota.c", "fota_check_parser.c", "fota_checkpoint.c", "crc32.c", "service_workspace.c"]
        command = [cc,"-std=c99","-Wall","-Wextra","-Werror","-Wno-dangling-else",
                   "-ffunction-sections","-fdata-sections","-DEC800M_HOST_TEST","-I",str(temp),"-I",str(ROOT/"include"),
                   str(temp/"harness.c"),*[str(ROOT/"src"/s) for s in sources],"-Wl,--gc-sections","-o",str(temp/"test.exe")]
        built = subprocess.run(command,capture_output=True,text=True)
        assert built.returncode==0,built.stderr
        run = subprocess.run([str(temp/"test.exe")],capture_output=True,text=True)
        assert run.returncode==0,run.stdout+run.stderr
        print(run.stdout.strip())


if __name__=="__main__":
    test_modem_handoff()
