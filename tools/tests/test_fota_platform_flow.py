"""Exercise production OTA, JSON parser, SHA/manifest and journal with a NOR/modem fake."""
import hashlib
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_flow(source, label="flow"):
    cc = shutil.which("gcc") or shutil.which("clang")
    assert cc, "host C compiler is required"
    with tempfile.TemporaryDirectory(prefix="fota_flow_") as directory:
        temp = Path(directory)
        stubs = {
            "config.h": '#ifndef CONFIG_H\n#define CONFIG_H\n#include <stdint.h>\nextern volatile uint32_t g_tick_ms;\n#define TICK_MS() g_tick_ms\n#define CFG_IP_LEN 64\n#define CFG_DEVICE_API_KEY_LEN 32\ntypedef struct {uint32_t fota_size;char fota_url[128];char device_api_key[32];} config_t;\nconfig_t *cfg_get(void);\n#endif\n',
            "flash_config.h": '#include "config.h"\n',
            "debug_uart.h": 'void dbg_printf(const char*,...);\n',
            "hw_init.h": 'void delay_ms(unsigned);\n',
            "n32l40x.h": 'void NVIC_SystemReset(void);\nvoid IWDG_ReloadKey(void);\n',
        }
        for name, text in stubs.items():
            (temp / name).write_text(text, encoding="ascii")
        harness = temp / "harness.c"
        harness.write_text(source, encoding="ascii")
        exe = temp / (label + ".exe")
        production = ["fota.c", "fota_check_parser.c", "fota_checkpoint.c", "crc32.c"]
        command = [cc, "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror",
                   "-I", str(temp), "-I", str(ROOT / "include"), "-I", str(ROOT),
                   *[str(ROOT / "src" / name) for name in production], str(harness), "-o", str(exe)]
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        print(result.stdout.strip())


HARNESS = r'''
#include <assert.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include "fota.h"
#include "fota_checkpoint.h"
#include "config.h"
#include "ec800m.h"
#include "ext_flash_store.h"
#include "service_workspace.h"
#include "boot_contract.h"
#include "build_version.h"
#include "firmware_layout.h"
#include "bootloader/include/image_manifest.h"
#include "crc32.h"
volatile uint32_t g_tick_ms;
static config_t cfg;
static uint8_t flash[2*1024*1024], workspace[512];
static int flash_owner, workspace_owner;
static bool ready, identity_ready, signature_ok, fail_bcr, bcr_read_verified, in_receive, fail_write;
static uint32_t fail_read_at;
static unsigned bcr_reads[2],fail_bcr_slot_read;
static const uint8_t *expected_signature_digest;
static tcp_state_t tcp;
static ec800m_recv_cb_t receive;
static unsigned opens,sends,closes,resets,erases,watchdogs,signature_calls;
static int open_error,send_error;
static uint32_t erased[256];
static char request[512],host[64],identity[12],logs[2048],events[4096];
static uint16_t port;
static unsigned event_count;
static void event(char c){assert(event_count+1<sizeof events);events[event_count++]=c;events[event_count]=0;}
config_t *cfg_get(void){return &cfg;}
bool ec800m_is_ready(void){return ready;}
bool terminal_identity_sync(char pid[12],char phone[13],char terminal[8]){
    if(!identity_ready)return false;
    strcpy(pid,identity);strcpy(phone,"012345678901");strcpy(terminal,"5678901");return true;
}
void ec800m_register_ota_recv(ec800m_recv_cb_t cb){receive=cb;}
int ec800m_tcp_open(uint8_t ch,const char *h,uint16_t p){assert(ch==1);++opens;strcpy(host,h);port=p;tcp=TCP_STATE_OPENING;return open_error;}
int ec800m_tcp_send(uint8_t ch,const uint8_t *p,uint16_t n){assert(ch==1 && tcp==TCP_STATE_OPEN);assert(n<sizeof request);memcpy(request,p,n);request[n]=0;++sends;return send_error;}
void ec800m_tcp_close(uint8_t ch){assert(ch==1 && !in_receive);++closes;tcp=TCP_STATE_CLOSED;event('C');}
tcp_state_t ec800m_tcp_state(uint8_t ch){assert(ch==1);return tcp;}
bool ec800m_ota_channel_prepare(void){if(tcp!=TCP_STATE_CLOSED)ec800m_tcp_close(1);return true;}
bool service_workspace_try_acquire(service_workspace_owner_t owner){if(workspace_owner)return false;workspace_owner=owner;return true;}
void service_workspace_release(service_workspace_owner_t owner){assert(workspace_owner==(int)owner);workspace_owner=0;event('W');}
uint8_t *service_workspace_buffer(size_t *n){if(n)*n=sizeof workspace;return workspace;}
bool ext_flash_try_lock(ext_flash_owner_t owner){if(flash_owner)return false;flash_owner=owner;return true;}
bool ext_flash_try_lock_now(ext_flash_owner_t owner){return ext_flash_try_lock(owner);}
void ext_flash_unlock(ext_flash_owner_t owner){assert(flash_owner==(int)owner);flash_owner=0;event('F');}
bool ext_flash_read(ext_flash_owner_t owner,uint32_t addr,void *out,uint32_t n){
    if(addr==BCR_SLOT_A_ADDR || addr==BCR_SLOT_B_ADDR){unsigned slot=addr==BCR_SLOT_B_ADDR;++bcr_reads[slot];if(slot && bcr_reads[slot]==fail_bcr_slot_read)return false;}
    assert((int)owner==flash_owner && addr+n<=sizeof flash);if(fail_read_at && addr==fail_read_at)return false;memcpy(out,flash+addr,n);
    if(n==sizeof(bcr_record_t) && (addr==BCR_SLOT_A_ADDR || addr==BCR_SLOT_B_ADDR)){
        bcr_record_t *b=out;
        if(b->state==BCR_PENDING && b->commit_marker==BCR_COMMIT_MARKER){bcr_read_verified=true;event('V');}
    }return true;
}
bool ext_flash_erase(ext_flash_owner_t owner,uint32_t addr,uint32_t n){
    assert((int)owner==flash_owner && n==4096 && addr%4096==0 && addr+n<=sizeof flash);
    if(fail_bcr && (addr==BCR_SLOT_A_ADDR || addr==BCR_SLOT_B_ADDR))return false;
    assert(erases<256);erased[erases++]=addr;event('E');memset(flash+addr,255,n);return true;
}
bool ext_flash_write_verified(ext_flash_owner_t owner,uint32_t addr,const void *in,uint32_t n){
    const uint8_t *p=in;assert((int)owner==flash_owner && addr+n<=sizeof flash);if(fail_write)return false;
    for(uint32_t i=0;i<n;i++){assert((flash[addr+i]&p[i])==p[i]);flash[addr+i]&=p[i];}return true;
}
bool firmware_signature_verify(const uint8_t *digest,const uint8_t *signature){
    (void)signature;if(expected_signature_digest)assert(!memcmp(digest,expected_signature_digest,32));++signature_calls;event('S');return signature_ok;
}
void IWDG_ReloadKey(void){++watchdogs;event('D');}
void NVIC_SystemReset(void){assert(!flash_owner && !workspace_owner && tcp==TCP_STATE_CLOSED);assert(bcr_read_verified);++resets;event('R');}
void delay_ms(unsigned n){(void)n;assert(!"reset may not use a delay");}
void dbg_printf(const char *format,...){va_list a;va_start(a,format);size_t n=strlen(logs);vsnprintf(logs+n,sizeof logs-n,format,a);va_end(a);}
static void fresh(void){
    memset(flash,255,sizeof flash);memset(&cfg,0,sizeof cfg);memset(workspace,0,sizeof workspace);
    strcpy(cfg.fota_url,"http://fota.lhhn.net");
    /* Synthetic key constructed at runtime; assertions never echo requests. */
    memset(cfg.device_api_key,'Q',20);cfg.device_api_key[20]=0;
    strcpy(identity,"12345678901");ready=identity_ready=signature_ok=true;
    flash_owner=workspace_owner=0;tcp=TCP_STATE_CLOSED;open_error=send_error=0;
    opens=sends=closes=resets=erases=watchdogs=signature_calls=0;
    fail_bcr=bcr_read_verified=in_receive=fail_write=false;fail_read_at=0;fail_bcr_slot_read=0;memset(bcr_reads,0,sizeof bcr_reads);expected_signature_digest=NULL;logs[0]=request[0]=events[0]=0;event_count=0;g_tick_ms=0;fota_init();
}
static void pump(unsigned count){while(count--){unsigned before=erases;fota_process();assert(erases-before<=1);}}
void connect_check(void){pump(2);assert(opens==1 && sends==0);tcp=TCP_STATE_OPEN;pump(1);assert(sends==1);}
static void bytes(const void *p,size_t n){assert(receive);in_receive=true;receive(1,p,(uint16_t)n);in_receive=false;}
static void response(const char *body){char wire[900];int n=snprintf(wire,sizeof wire,"HTTP/1.1 200 OK\r\nContent-Length: %u\r\nContent-Type: application/json\r\n\r\n%s",(unsigned)strlen(body),body);assert(n>0 && n<(int)sizeof wire);bytes(wire,(size_t)n);pump(1);}
void no_update(void){response("{\"updateAvailable\":false}");assert(fota_get_state()==FOTA_STATE_IDLE);assert(!workspace_owner && !flash_owner);}
void update_metadata(uint32_t version,uint32_t size,const char *url,const char *sha256,const char *signature){char body[512];snprintf(body,sizeof body,"{\"updateAvailable\":true,\"versionCode\":%lu,\"size\":%lu,\"downloadUrl\":\"%s\",\"sha256\":\"%s\",\"signature\":\"%s\",\"signingKeyId\":1,\"downloadToken\":\"task-token-123\"}",(unsigned long)version,(unsigned long)size,url,sha256,signature);response(body);}
void update(uint32_t version,uint32_t size,const char *url){update_metadata(version,size,url,"000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f","202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f404142434445464748494a4b4c4d4e4f505152535455565758595a5b5c5d5e5f");}
void download_open(void){unsigned initial=sends;for(unsigned i=0;i<140 && opens<2;i++)pump(1);assert(opens==2 && sends==initial);tcp=TCP_STATE_OPEN;pump(1);assert(sends==initial+1);}
void seed_bcr(uint8_t state){bcr_record_t b;memset(&b,0,sizeof b);b.magic=BCR_MAGIC;b.sequence=8;b.state=state;b.image_version=3001;b.commit_marker=BCR_COMMIT_MARKER;b.crc32=crc32_compute(&b,offsetof(bcr_record_t,crc32));memcpy(flash+BCR_SLOT_A_ADDR,&b,sizeof b);}
void assert_auth(void){char expected[80];snprintf(expected,sizeof expected,"\r\nX-Device-Key: %s\r\n",cfg.device_api_key);assert(strstr(request,expected));assert(!strstr(logs,cfg.device_api_key));}
'''


FLOW_CASES = r'''
int main(void){
    fresh();cfg.device_api_key[0]=0;pump(10);assert(!opens && !workspace_owner && !flash_owner);
    fresh();ready=false;pump(10);assert(!opens);ready=true;identity_ready=false;pump(10);assert(!opens);identity_ready=true;connect_check();
    assert(!strcmp(host,"fota.lhhn.net") && port==80);
    assert(strstr(request,"GET /api/device/updates/check?deviceId=12345678901&deviceModel=A300-406&currentVersionCode=3002 HTTP/1.1\r\nHost: fota.lhhn.net\r\n"));assert_auth();no_update();
    uint32_t done=g_tick_ms;pump(4);assert(opens==1);g_tick_ms=done+21599999U;pump(1);assert(opens==1);g_tick_ms=done+21600000U;pump(2);assert(opens==2);
    fresh();g_tick_ms=0xff000000U;connect_check();no_update();done=g_tick_ms;g_tick_ms=done+21599999U;pump(1);assert(opens==1);g_tick_ms=done+21600000U;pump(2);assert(opens==2);
    fresh();connect_check();no_update();assert(fota_request_check());pump(2);assert(opens==2);
    fresh();strcpy(identity,"a b&/?+=%#");connect_check();assert(strstr(request,"deviceId=a%20b%26%2F%3F%2B%3D%25%23&deviceModel=A300-406"));
    for(unsigned i=0;i<2;i++){fresh();seed_bcr(i?BCR_PENDING:BCR_TRIAL);pump(10);assert(!opens && !workspace_owner);}
    fresh();workspace_owner=SERVICE_WORKSPACE_OWNER_DIAGNOSTIC;pump(3);assert(!opens);workspace_owner=0;flash_owner=EXT_FLASH_OWNER_CONFIG;pump(3);assert(!opens);flash_owner=0;connect_check();
    /* Async connect has a fixed 30 s deadline; response has a fixed 60 s deadline. */
    fresh();pump(2);g_tick_ms=29999;pump(1);assert(opens==1);g_tick_ms=30000;pump(1);g_tick_ms=31000;pump(2);assert(opens==2);
    fresh();open_error=-1;for(unsigned i=0;i<80;i++){pump(1);g_tick_ms+=1000;}assert(opens==3 && !sends && fota_get_state()==FOTA_STATE_IDLE);assert(!workspace_owner && !flash_owner);
    fresh();send_error=-1;for(unsigned i=0;i<80;i++){if(tcp==TCP_STATE_OPENING)tcp=TCP_STATE_OPEN;pump(1);g_tick_ms+=1000;}assert(opens==3 && sends==3 && fota_get_state()==FOTA_STATE_IDLE);
    fresh();connect_check();for(unsigned i=0;i<200;i++){pump(1);g_tick_ms+=1000;if(tcp==TCP_STATE_OPENING)tcp=TCP_STATE_OPEN;}assert(opens==3 && sends==3 && fota_get_state()==FOTA_STATE_IDLE);
    const char *wire="HTTP/1.1 200 OK\r\nContent-Length: 25\r\nContent-Type: application/json\r\n\r\n{\"updateAvailable\":false}";
    for(size_t split=1;split<strlen(wire);split++){fresh();connect_check();bytes(wire,split);bytes(wire+split,strlen(wire)-split);pump(1);assert(fota_get_state()==FOTA_STATE_IDLE && opens==1);}
    fresh();connect_check();for(size_t i=0;i<strlen(wire);i++)bytes(wire+i,1);pump(1);assert(fota_get_state()==FOTA_STATE_IDLE);
    const char *bad[]={
      "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{}",
      "HTTP/1.1 200 OK\r\nContent-Length: 0\r\nContent-Type: application/json\r\n\r\n",
      "HTTP/1.1 200 OK\r\nContent-Length: 1024\r\nContent-Type: application/json\r\n\r\n",
      "HTTP/1.1 200 OK\r\nContent-Length: 25\r\nTransfer-Encoding: chunked\r\nContent-Type: application/json\r\n\r\n",
      "HTTP/1.1 200 OK\r\nContent-Length: 25\r\nContent-Length: 25\r\nContent-Type: application/json\r\n\r\n",
      "HTTP/1.1 200 OK\r\nContent-Length: 25junk\r\nContent-Type: application/json\r\n\r\n",
      "HTTP/1.0 200 OK\r\nContent-Length: 25\r\nContent-Type: application/json\r\n\r\n",
      "HTTP/1.1 200 OK\r\nContent-Length: 25\r\nContent-Type: text/html\r\n\r\n",
      "HTTP/1.1 302 Found\r\nContent-Length: 25\r\nLocation: http://evil.invalid\r\n\r\n",
      "HTTP/1.1 401 Unauthorized\r\nContent-Length: 25\r\n\r\n"
    };
    for(unsigned i=0;i<sizeof bad/sizeof bad[0];i++){fresh();connect_check();bytes(bad[i],strlen(bad[i]));pump(5);assert(fota_get_state()==FOTA_STATE_IDLE && erases==0 && opens==1);assert_auth();}
    fresh();connect_check();char huge[1100];memset(huge,'A',sizeof huge);bytes(huge,sizeof huge);pump(1);assert(fota_get_state()==FOTA_STATE_IDLE && erases==0);
    fresh();connect_check();char excess[300];snprintf(excess,sizeof excess,"%sx",wire);bytes(excess,strlen(excess));pump(1);assert(fota_get_state()==FOTA_STATE_IDLE && erases==0);
    fresh();connect_check();bytes(wire,strlen(wire)-5);tcp=TCP_STATE_CLOSED;pump(1);g_tick_ms=1000;pump(2);assert(opens==2 && erases==0);
    fresh();connect_check();for(unsigned i=0;i<3;i++){const char *e="HTTP/1.1 500 Error\r\nContent-Length: 0\r\n\r\n";bytes(e,strlen(e));pump(1);if(i<2){g_tick_ms+=(i+1)*1000;pump(2);tcp=TCP_STATE_OPEN;pump(1);}}assert(opens==3 && fota_get_state()==FOTA_STATE_IDLE);
    for(unsigned i=0;i<6;i++){fresh();connect_check();update(i<2?3001+i:3003,i==5?0:4300,i==2?"http://evil.invalid/fw":i==3?"http://fota.lhhn.net:81/fw":i==4?"https://fota.lhhn.net/fw":"http://fota.lhhn.net/fw");assert(fota_get_state()==FOTA_STATE_IDLE && erases==0);}
    fresh();connect_check();update(3003,4300,"http://fota.lhhn.net/api/device/updates/tasks/17/download");assert(workspace_owner==SERVICE_WORKSPACE_OWNER_OTA && flash_owner==EXT_FLASH_OWNER_OTA);download_open();assert_auth();assert(strstr(request,"GET /api/device/updates/tasks/17/download HTTP/1.1\r\n"));assert(erases==3);assert(erased[1]==0x10000 && erased[2]==0x11000);assert(strstr(events,"DED"));
    fresh();connect_check();update(3003,4300,"http://fota.lhhn.net/fw");download_open();
    const char *download_header="HTTP/1.1 200 OK\r\nContent-Length: 4300\r\n\r\n";bytes(download_header,strlen(download_header));
    fail_write=true;bytes("x",1);pump(1);assert(fota_get_state()==FOTA_STATE_ERROR && !flash_owner);
    fresh();connect_check();update(3003,4300,"http://fota.lhhn.net/fw");download_open();
    fail_read_at=FOTA_CHECKPOINT_SLOT_A;tcp=TCP_STATE_CLOSED;pump(1);assert(fota_get_state()==FOTA_STATE_ERROR && !flash_owner);
    puts("flow: gates/auth/encoding/wrap/deadlines/three attempts/fragmentation/HTTP rejection/same origin PASS");return 0;
}
'''


def test_platform_flow():
    run_flow(HARNESS + FLOW_CASES)


def test_verified_reset():
    # A candidate is an executable Cortex-M4 image, not merely signed bytes.
    # Keep this fixture bootable so the negative vector case below is isolated.
    payload = struct.pack("<II", 0x20001000, 0x08006009) + b"verified image body" * 20
    header = struct.pack("<5I12s", 0xA300B007, 3003, len(payload),
                         zlib.crc32(payload), 0x41333030, bytes(12))
    package = header + payload
    data = ",".join(str(v) for v in package)
    package_digest = hashlib.sha256(package).digest()
    digest = ",".join(str(v) for v in package_digest)
    digest_hex = package_digest.hex()
    signature_hex = bytes([0x5A]) * 64
    code = r'''
static const uint8_t package[]={__PACKAGE__};
static const uint8_t canonical_digest[]={__DIGEST__};
static const uint8_t invalid_package[]={__INVALID_PACKAGE__};
static const uint8_t invalid_canonical_digest[]={__INVALID_DIGEST__};
int main(void){
    for(unsigned scenario=0;scenario<8;scenario++){
        fresh();expected_signature_digest=canonical_digest;connect_check();update_metadata(scenario==1?3004:3003,sizeof package,"http://fota.lhhn.net/fw","__SHA256__","__SIGNATURE__");download_open();
        if(scenario==2)signature_ok=false;
        if(scenario==3)fail_bcr=true;
        char header[150];snprintf(header,sizeof header,"HTTP/1.1 200 OK\r\nContent-Length: %u\r\nContent-Type: application/octet-stream\r\n\r\n",(unsigned)sizeof package);bytes(header,strlen(header));
        uint8_t copy[sizeof package];memcpy(copy,package,sizeof copy);
        if(scenario==4)copy[sizeof copy-1]^=1;
        if(scenario==5)copy[12]^=1;
        if(scenario==6){bytes(copy,sizeof copy-1);tcp=TCP_STATE_CLOSED;pump(1);assert(!resets);continue;}
        bytes(copy,sizeof copy);assert(!resets);if(scenario==7)bytes("x",1);pump(2);
        if(scenario==0){bcr_record_t b;memcpy(&b,flash+BCR_SLOT_B_ADDR,sizeof b);assert(resets==1 && signature_calls==1);assert(b.state==BCR_PENDING && b.image_version==3003 && b.transaction_length==sizeof package-FOTA_PACKAGE_HEADER_SIZE);assert(strstr(events,"VFWCDR"));assert(strchr(events,'S')<strchr(events,'V'));}
        else assert(!resets && fota_get_state()==FOTA_STATE_ERROR && !flash_owner && !workspace_owner);
        assert(!strstr(logs,cfg.device_api_key));
    }
    /* The package is otherwise signed, hashed and CRC-valid, but its reset
       vector is non-Thumb. It must never hand a bad executable to BCR. */
    fresh();expected_signature_digest=invalid_canonical_digest;connect_check();update_metadata(3003,sizeof invalid_package,"http://fota.lhhn.net/fw","__INVALID_SHA256__","__SIGNATURE__");download_open();
    char header[150];snprintf(header,sizeof header,"HTTP/1.1 200 OK\r\nContent-Length: %u\r\nContent-Type: application/octet-stream\r\n\r\n",(unsigned)sizeof invalid_package);bytes(header,strlen(header));bytes(invalid_package,sizeof invalid_package);pump(1);
    assert(signature_calls==1 && resets==0 && fota_get_state()==FOTA_STATE_ERROR && !flash_owner && !workspace_owner && !bcr_read_verified);
    puts("verified reset: actual manifest/hash/CRC/signature gate/advertised metadata/BCR readback/resource-close-watchdog-reset ordering PASS");return 0;
}
'''.replace("__PACKAGE__", data).replace("__DIGEST__", digest).replace("__SHA256__", digest_hex).replace("__SIGNATURE__", signature_hex.hex())
    invalid_payload = struct.pack("<II", 0x20001000, 0x08006008) + b"verified image body" * 20
    invalid_header = struct.pack("<5I12s", 0xA300B007, 3003, len(invalid_payload),
                                 zlib.crc32(invalid_payload), 0x41333030, bytes(12))
    invalid_package = invalid_header + invalid_payload
    invalid_canonical = hashlib.sha256(invalid_package).digest()
    code = code.replace("__INVALID_PACKAGE__", ",".join(str(v) for v in invalid_package))
    code = code.replace("__INVALID_DIGEST__", ",".join(str(v) for v in invalid_canonical))
    code = code.replace("__INVALID_SHA256__", invalid_canonical.hex())
    run_flow(HARNESS + code, "verified_reset")


def test_bcr_read_failure_gate():
    run_flow(HARNESS + r'''
int main(void){
    for(unsigned state=0;state<2;state++)for(unsigned fail=1;fail<=2;fail++){
        fresh();seed_bcr(state?BCR_PENDING:BCR_TRIAL);
        memcpy(flash+BCR_SLOT_B_ADDR,flash+BCR_SLOT_A_ADDR,sizeof(bcr_record_t));
        seed_bcr(BCR_ACTIVE);bcr_record_t *old=(bcr_record_t*)(flash+BCR_SLOT_A_ADDR);
        old->sequence=7;old->crc32=crc32_compute(old,offsetof(bcr_record_t,crc32));
        fail_bcr_slot_read=fail;pump(1);
        assert(!opens && !workspace_owner && !flash_owner);
        assert(bcr_reads[0]==1 && bcr_reads[1]==1);
        pump(1);assert(!opens && !workspace_owner);
    }
    puts("BCR admission: one read per slot, newer TRIAL/PENDING and second-slot I/O failure closed PASS");return 0;
}
''', "bcr_admission")


def test_early_etag_retry():
    run_flow(HARNESS + r'''
int main(void){
    for(unsigned partial=0;partial<2;partial++){
        fresh();connect_check();update(3003,4300,"http://fota.lhhn.net/fw");download_open();
        const char *h="HTTP/1.1 200 OK\r\nContent-Length: 4300\r\nETag: newly-learned\r\n\r\n";
        bytes(h,strlen(h));if(partial)bytes("partial",7);
        tcp=TCP_STATE_CLOSED;pump(1);assert(fota_get_state()==FOTA_STATE_PREPARING);
        g_tick_ms+=1000;for(unsigned i=0;i<10 && opens<3;i++)pump(1);
        assert(opens==3);tcp=TCP_STATE_OPEN;pump(1);assert(sends==3);
        assert(!strstr(request,"Range:") && !strstr(request,"If-Range:"));assert_auth();
        for(unsigned i=0;i<8192;i++)assert(flash[0x10000+i]==255);
    }
    puts("ETag: disconnect before body/within first sector restarts safely at zero PASS");return 0;
}
''', "early_etag")


def test_rearm_and_download_deadline():
    run_flow(HARNESS + r'''
int main(void){
    for(unsigned rearm=0;rearm<2;rearm++){
        fresh();connect_check();g_tick_ms=700;
        if(rearm)assert(fota_request_check());
        update(3003,4300,"http://fota.lhhn.net/fw");download_open();
        g_tick_ms=5000;
        const char *bad="HTTP/1.1 401 Unauthorized\r\nContent-Length: 25\r\n\r\n";
        bytes(bad,strlen(bad));pump(1);assert(fota_get_state()==FOTA_STATE_ERROR);
        if(rearm){pump(2);assert(opens==3);}
        else{g_tick_ms=700+21599999;pump(2);assert(opens==2);g_tick_ms=700+21600000;pump(2);assert(opens==3);}
    }
    puts("check scheduling: active rearm retained, six hours starts at accepted check response PASS");return 0;
}
''', "rearm_deadline")


if __name__ == "__main__":
    test_platform_flow()
    test_verified_reset()
    test_bcr_read_failure_gate()
    test_early_etag_retry()
    test_rearm_and_download_deadline()
    print("test_fota_platform_flow: PASS")
