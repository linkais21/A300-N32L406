#include "fota.h"
#include "fota_checkpoint.h"
#include "fota_check_parser.h"
#include "terminal_identity.h"
#include "build_version.h"
#include "crc32.h"
#include "ec800m.h"
#include "ext_flash_store.h"
#include "flash_config.h"
#include "debug_uart.h"
#include "hw_init.h"
#include "config.h"
#include "firmware_signature.h"
#include "trusted_public_key.h"
#include "n32l40x.h"
#include "boot_contract.h"
#include "firmware_layout.h"
#include "service_workspace.h"
#include <stddef.h>
#include <string.h>
#include <stdio.h>

#ifndef EC800M_H
typedef void (*ec800m_recv_cb_t)(uint8_t, const uint8_t *, uint16_t);
#endif

#define FOTA_TCP_CH EC800M_CH_OTA
#define FOTA_RX_TIMEOUT_MS 60000UL
#define FOTA_CONNECT_TIMEOUT_MS 30000UL
#define FOTA_CHECK_INTERVAL_MS 21600000UL
#define FOTA_TRANSPORT_ATTEMPTS 3U
#define FOTA_HTTP_LIMIT (SERVICE_WORKSPACE_CAPACITY - 1U)
#define FOTA_TRIAL_HEALTHY_MS 30000UL
typedef enum { FOTA_OP_CHECK, FOTA_OP_DOWNLOAD } fota_operation_t;
typedef enum { FOTA_HTTP_OK, FOTA_HTTP_INVALID, FOTA_HTTP_TRANSPORT } fota_http_error_t;
static fota_state_t s_state = FOTA_STATE_IDLE;
static fota_operation_t s_operation;
static fota_http_error_t s_http_error;
static uint32_t s_expected, s_received, s_crc = 0xFFFFFFFFUL;
static uint32_t s_erase_offset, s_erase_end;
static uint32_t s_version, s_deadline, s_retry_due, s_next_check;
static char s_url[128], s_etag[40], s_host[CFG_IP_LEN], s_path[256];
static uint16_t s_port;
static bool s_header_done, s_ota_lock, s_workspace_lock;
static bool s_trial_checked, s_check_armed, s_connect_started, s_body_complete;
static bool s_restart_zero;
static uint8_t s_attempts;
static uint16_t s_http_header_len, s_http_body_len, s_check_length;
static uint8_t s_package_sha256[32], s_signature[64];
static uint32_t s_signing_key_id;
static bool s_authorization_committed;

static char *fota_http_header(void)
{
    return (char *)service_workspace_buffer(NULL);
}

/* Host/unit-test builds may provide only the legacy EC800M surface. */
__attribute__((weak)) void ec800m_register_ota_recv(ec800m_recv_cb_t cb) { (void)cb; }

typedef struct { uint32_t h[8]; uint64_t bits; uint8_t block[64], used; } fota_sha256_t;
static uint32_t fota_rotr(uint32_t x,uint8_t n){return (x>>n)|(x<<(32U-n));}
static void fota_sha_block(fota_sha256_t *c,const uint8_t *p){
    static const uint32_t k[64]={
        0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
        0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
        0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
        0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
        0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
        0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
        0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
        0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
    uint32_t w[64],a,b,d,e,f,g,h,cc,t1,t2; uint8_t i;
    for(i=0;i<16;i++)w[i]=((uint32_t)p[4*i]<<24)|((uint32_t)p[4*i+1]<<16)|((uint32_t)p[4*i+2]<<8)|p[4*i+3];
    for(i=16;i<64;i++){uint32_t q=fota_rotr(w[i-15],7)^fota_rotr(w[i-15],18)^(w[i-15]>>3),r=fota_rotr(w[i-2],17)^fota_rotr(w[i-2],19)^(w[i-2]>>10);w[i]=w[i-16]+q+w[i-7]+r;}
    a=c->h[0];b=c->h[1];cc=c->h[2];d=c->h[3];e=c->h[4];f=c->h[5];g=c->h[6];h=c->h[7];
    for(i=0;i<64;i++){uint32_t q=fota_rotr(e,6)^fota_rotr(e,11)^fota_rotr(e,25),ch=(e&f)^(~e&g),r=fota_rotr(a,2)^fota_rotr(a,13)^fota_rotr(a,22),maj=(a&b)^(a&cc)^(b&cc);t1=h+q+ch+k[i]+w[i];t2=r+maj;h=g;g=f;f=e;e=d+t1;d=cc;cc=b;b=a;a=t1+t2;}
    c->h[0]+=a;c->h[1]+=b;c->h[2]+=cc;c->h[3]+=d;c->h[4]+=e;c->h[5]+=f;c->h[6]+=g;c->h[7]+=h;
}
static void fota_sha_init(fota_sha256_t *c){static const uint32_t h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};memcpy(c->h,h,sizeof h);c->bits=0;c->used=0;}
static void fota_sha_update(fota_sha256_t *c,const uint8_t *p,uint32_t n){c->bits+=n*8U;while(n){uint32_t room=64U-c->used,t=n<room?n:room;memcpy(c->block+c->used,p,t);c->used+=(uint8_t)t;p+=t;n-=t;if(c->used==64){fota_sha_block(c,c->block);c->used=0;}}}
static void fota_sha_final(fota_sha256_t *c,uint8_t out[32]){uint8_t i;c->block[c->used++]=0x80;while(c->used!=56){if(c->used==64){fota_sha_block(c,c->block);c->used=0;}c->block[c->used++]=0;}for(i=0;i<8;i++)c->block[56+i]=(uint8_t)(c->bits>>(56-8*i));fota_sha_block(c,c->block);for(i=0;i<8;i++){out[4*i]=(uint8_t)(c->h[i]>>24);out[4*i+1]=(uint8_t)(c->h[i]>>16);out[4*i+2]=(uint8_t)(c->h[i]>>8);out[4*i+3]=(uint8_t)c->h[i];}}

static bool parse_url(const char *url, char *host, uint16_t *port, char *path)
{
    const char *p; uint16_t n=0; uint32_t number=0;
    if (!url || strncmp(url,"http://",7)!=0 || strlen(url)>=128U) return false;
    p=url+7;
    while (*p && *p!='/' && *p!=':') {
        char c=*p++;
        if (!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||
              (c>='0'&&c<='9')||c=='.'||c=='-') || n>=CFG_IP_LEN-1U) return false;
        host[n++]=(c>='A'&&c<='Z')?(char)(c+'a'-'A'):c;
    }
    host[n]=0; if (!n) return false; *port=80U;
    if (*p==':') {
        ++p; if (*p<'0'||*p>'9') return false;
        while (*p>='0'&&*p<='9') {number=number*10U+(uint32_t)(*p++-'0');if(number>65535U)return false;}
        if (!number) return false;
        *port=(uint16_t)number;
    }
    if (*p && *p!='/') return false;
    for (const char *q=p;*q;++q) if ((uint8_t)*q<=0x20U || (uint8_t)*q>=0x7fU || *q=='#' || *q=='\\') return false;
    strcpy(path,*p?p:"/"); return true;
}

static bool same_origin(const char *url)
{
    char base_host[CFG_IP_LEN], host[CFG_IP_LEN], path[128]; uint16_t base_port, port;
    return parse_url(cfg_get()->fota_url,base_host,&base_port,path) &&
           parse_url(url,host,&port,path) && base_port==port && strcmp(base_host,host)==0;
}

static bool key_valid(void)
{
    const char *key=cfg_get()->device_api_key; unsigned n;
    for(n=0;n<CFG_DEVICE_API_KEY_LEN && key[n];++n)
        if((uint8_t)key[n]<0x20U || (uint8_t)key[n]>0x7eU) return false;
    return n>=16U && n<CFG_DEVICE_API_KEY_LEN;
}

static bool encode_query(const char *in, char *out, size_t capacity)
{
    static const char hex[]="0123456789ABCDEF"; size_t n=0;
    while(*in) {
        uint8_t c=(uint8_t)*in++;
        bool plain=(c>='a'&&c<='z')||(c>='A'&&c<='Z')||
                   (c>='0'&&c<='9')||c=='-'||c=='_'||c=='.'||c=='~';
        if(n+(plain?1U:3U)>=capacity)return false;
        if(plain)out[n++]=(char)c;
        else {out[n++]='%';out[n++]=hex[c>>4];out[n++]=hex[c&15U];}
    }
    out[n]=0;return true;
}

static void http_reset(void)
{
    s_header_done=false;s_http_header_len=0;s_http_body_len=0;s_check_length=0;
    s_body_complete=false;s_restart_zero=false;s_http_error=FOTA_HTTP_OK;
    fota_http_header()[0]=0;
}

static void fota_ec800m_rx(uint8_t ch, const uint8_t *data, uint16_t len)
{
    if(ch==FOTA_TCP_CH && data && len && s_workspace_lock &&
       s_state==FOTA_STATE_VERIFYING) {s_http_error=FOTA_HTTP_INVALID;return;}
    if(ch!=FOTA_TCP_CH || !data || !s_workspace_lock || s_http_error!=FOTA_HTTP_OK ||
       (s_state!=FOTA_STATE_CHECKING && s_state!=FOTA_STATE_DOWNLOADING))return;
    while(len && !s_header_done) {
        if(s_http_header_len>=FOTA_HTTP_LIMIT || *data==0) {s_http_error=FOTA_HTTP_INVALID;return;}
        fota_http_header()[s_http_header_len++]=(char)*data++;--len;
        fota_http_header()[s_http_header_len]=0;
        if(s_http_header_len>=4U && !memcmp(fota_http_header()+s_http_header_len-4U,"\r\n\r\n",4U)) {
            fota_on_http_header(fota_http_header());
            if(s_http_error!=FOTA_HTTP_OK || s_restart_zero)return;
            s_header_done=true;fota_http_header()[0]=0;
        }
    }
    if(!len || !s_header_done)return;
    if(s_operation==FOTA_OP_DOWNLOAD) {fota_on_chunk(data,len,s_received);return;}
    if(len>s_check_length-s_http_body_len) {s_http_error=FOTA_HTTP_INVALID;return;}
    memcpy(fota_http_header()+s_http_body_len,data,len);s_http_body_len=(uint16_t)(s_http_body_len+len);
    fota_http_header()[s_http_body_len]=0;s_body_complete=(s_http_body_len==s_check_length);
}

static bool send_request(void)
{
    char req[512],authority[72],range[90];int n;
    if(!key_valid())return false;
    n=s_port==80U?snprintf(authority,sizeof authority,"%s",s_host):snprintf(authority,sizeof authority,"%s:%u",s_host,s_port);
    if(n<0 || (size_t)n>=sizeof authority)return false;
    range[0]=0;
    if(s_operation==FOTA_OP_DOWNLOAD && s_received) {
        n=snprintf(range,sizeof range,"Range: bytes=%lu-\r\n%s%s%s",(unsigned long)s_received,
                   s_etag[0]?"If-Range: ":"",s_etag,s_etag[0]?"\r\n":"");
        if(n<0 || (size_t)n>=sizeof range)return false;
    }
    n=snprintf(req,sizeof req,"GET %s HTTP/1.1\r\nHost: %s\r\nX-Device-Key: %s\r\n%sConnection: close\r\n\r\n",
               s_path,authority,cfg_get()->device_api_key,range);
    if(n<0 || (size_t)n>=sizeof req)return false;
    /* Request and response bodies are never debug-logged. */
    return ec800m_tcp_send(FOTA_TCP_CH,(const uint8_t *)req,(uint16_t)n)==0;
}

static bool checkpoint_load(void)
{
    fota_checkpoint_t c;
    if (!s_ota_lock || !fota_checkpoint_load(s_url,s_expected,&c)) return false;
    /* Offset zero retains no candidate bytes, so a newly learned response
     * ETag may safely be discarded when retrying before the first boundary. */
    if ((c.offset && s_etag[0] && strcmp(c.etag,s_etag)!=0) || (s_version && c.version!=s_version)) return false;
    s_received=c.offset; s_version=c.version; s_crc=c.running_crc;
    strncpy(s_etag,c.etag,sizeof s_etag-1); s_etag[sizeof s_etag-1]=0; return true;
}
static bool checkpoint_save(void)
{
    fota_checkpoint_t c;bool committed;
    memset(&c,0,sizeof c); c.offset=s_received; c.expected_length=s_expected;
    c.version=s_version; c.running_crc=s_crc;
    memcpy(c.url,s_url,sizeof c.url); memcpy(c.etag,s_etag,sizeof c.etag);
    if(!s_ota_lock)return false;
    IWDG_ReloadKey();committed=fota_checkpoint_commit(&c);IWDG_ReloadKey();
    return committed;
}

static bool due(uint32_t now, uint32_t deadline) { return (int32_t)(now-deadline)>=0; }
static void fail_download(void);

static void schedule_tail_cleanup(void)
{
    s_erase_offset = s_received;
    s_erase_end = (s_expected + FLASH_SECTOR_SIZE - 1U) & ~(FLASH_SECTOR_SIZE - 1U);
    http_reset();s_connect_started=false;s_state=FOTA_STATE_PREPARING;
}

__attribute__((weak)) uint32_t fota_product_id(void) { return 0x41333030UL; }
__attribute__((weak)) uint32_t fota_hardware_id(void) { return 0x343036UL; }

static bool fota_bcr_valid(const bcr_record_t *record)
{
    bcr_record_t copy;
    if (record == NULL || record->magic != BCR_MAGIC ||
        record->commit_marker != BCR_COMMIT_MARKER)
        return false;
    copy = *record;
    copy.crc32 = 0U;
    copy.commit_marker = 0xFFFFFFFFUL;
    return crc32_compute(&copy, (uint32_t)offsetof(bcr_record_t, crc32)) ==
           record->crc32;
}

static bool fota_sequence_newer(uint32_t a,uint32_t b){return (int32_t)(a-b)>0;}

typedef enum { FOTA_BCR_IO_ERROR=-1, FOTA_BCR_ABSENT=0, FOTA_BCR_FOUND=1 } fota_bcr_result_t;

static fota_bcr_result_t fota_bcr_load(bcr_record_t *out)
{
    bcr_record_t a,b; bool va,vb;
    if(!out)return FOTA_BCR_IO_ERROR;
    if(!ext_flash_read(EXT_FLASH_OWNER_OTA,BCR_SLOT_A_ADDR,&a,sizeof a) ||
       !ext_flash_read(EXT_FLASH_OWNER_OTA,BCR_SLOT_B_ADDR,&b,sizeof b))return FOTA_BCR_IO_ERROR;
    va=fota_bcr_valid(&a);vb=fota_bcr_valid(&b);
    if(!va&&!vb)return FOTA_BCR_ABSENT;
    *out=(!vb||(va&&fota_sequence_newer(a.sequence,b.sequence)))?a:b;
    return FOTA_BCR_FOUND;
}

static bool fota_bcr_write_record(const bcr_record_t *record)
{
    bcr_record_t r=*record,check,a,b; bool va,vb; uint32_t addr;
    bool erased;
    if(!ext_flash_read(EXT_FLASH_OWNER_OTA,BCR_SLOT_A_ADDR,&a,sizeof a) ||
       !ext_flash_read(EXT_FLASH_OWNER_OTA,BCR_SLOT_B_ADDR,&b,sizeof b))return false;
    va=fota_bcr_valid(&a);vb=fota_bcr_valid(&b);
    if(!va&&!vb)addr=(r.sequence&1U)?BCR_SLOT_B_ADDR:BCR_SLOT_A_ADDR;
    else if(!va)addr=BCR_SLOT_A_ADDR;
    else if(!vb)addr=BCR_SLOT_B_ADDR;
    else addr=fota_sequence_newer(a.sequence,b.sequence)?BCR_SLOT_B_ADDR:BCR_SLOT_A_ADDR;
    r.magic=BCR_MAGIC;r.commit_marker=0xFFFFFFFFUL;r.crc32=0U;
    r.crc32=crc32_compute(&r,(uint32_t)offsetof(bcr_record_t,crc32));
    IWDG_ReloadKey();erased=ext_flash_erase(EXT_FLASH_OWNER_OTA,addr,FLASH_SECTOR_SIZE);IWDG_ReloadKey();
    if(!erased||
       !ext_flash_write_verified(EXT_FLASH_OWNER_OTA,addr,&r,(uint32_t)offsetof(bcr_record_t,commit_marker)))return false;
    r.commit_marker=BCR_COMMIT_MARKER;
    if(!ext_flash_write_verified(EXT_FLASH_OWNER_OTA,addr+offsetof(bcr_record_t,commit_marker),&r.commit_marker,sizeof r.commit_marker)||
       !ext_flash_read(EXT_FLASH_OWNER_OTA,addr,&check,sizeof check))return false;
    return fota_bcr_valid(&check)&&memcmp(&check,&r,sizeof r)==0;
}

bool fota_verify_manifest(const void *manifest, uint32_t length)
{
    const fota_package_header_t *m=(const fota_package_header_t *)manifest; fota_sha256_t sha; uint8_t digest[32], buf[256]; uint32_t left,addr,body_crc=0xFFFFFFFFUL;
    bcr_record_t current; uint32_t floor=0U;fota_bcr_result_t bcr;
    static const uint8_t zero[12]={0};
    if (!m || length<sizeof *m || m->magic!=FOTA_PACKAGE_HEADER_MAGIC ||
        m->product_id!=FOTA_PACKAGE_PRODUCT_ID || m->product_id!=fota_product_id() ||
        memcmp(m->reserved,zero,sizeof zero)!=0 || m->version==0U ||
        m->body_size<8U || m->body_size>APP_FLASH_SIZE ||
        m->body_size>FOTA_MAX_SIZE-sizeof *m ||
        s_expected!=(uint32_t)sizeof *m+m->body_size ||
        s_signing_key_id!=TRUSTED_SIGNING_KEY_ID) return false;
    bcr=fota_bcr_load(&current);if(bcr==FOTA_BCR_IO_ERROR)return false;
    if(bcr==FOTA_BCR_FOUND)floor=current.rollback_floor;
    if(m->version<floor)return false;
    fota_sha_init(&sha); left=s_expected; addr=FOTA_FLASH_ADDR;
    while(left){uint32_t n=left>sizeof buf?sizeof buf:left; IWDG_ReloadKey();if(!ext_flash_read(EXT_FLASH_OWNER_OTA,addr,buf,n))return false; fota_sha_update(&sha,buf,n); addr+=n; left-=n;}
    fota_sha_final(&sha,digest);
    if (memcmp(digest,s_package_sha256,sizeof digest)!=0 ||
        !firmware_signature_verify(digest,s_signature)) return false;
    left=m->body_size;addr=FOTA_FLASH_ADDR+sizeof *m;
    while(left){uint32_t n=left>sizeof buf?sizeof buf:left;if(!ext_flash_read(EXT_FLASH_OWNER_OTA,addr,buf,n))return false;body_crc=crc32_update(body_crc,buf,n);addr+=n;left-=n;}
    if((~body_crc)!=m->body_crc32)return false;
    uint8_t vectors[8];
    if (!ext_flash_read(EXT_FLASH_OWNER_OTA, FOTA_FLASH_ADDR + sizeof *m, vectors, sizeof vectors)) return false;
    uint32_t msp = ((uint32_t)vectors[0]) | ((uint32_t)vectors[1] << 8) | ((uint32_t)vectors[2] << 16) | ((uint32_t)vectors[3] << 24);
    uint32_t reset = ((uint32_t)vectors[4]) | ((uint32_t)vectors[5] << 8) | ((uint32_t)vectors[6] << 16) | ((uint32_t)vectors[7] << 24);
    if (msp < 0x20000000UL || msp > 0x20006000UL || (msp & 7U) != 0U ||
        reset < APP_FLASH_BASE + 1UL || reset >= (APP_FLASH_BASE + m->body_size) || (reset & 1U) == 0U) return false;
    return true;
}

bool fota_bcr_commit_pending(uint32_t version, uint32_t length, uint32_t target)
{
    bcr_record_t r, old;fota_bcr_result_t bcr;
    memset(&r,0,sizeof r); r.magic=BCR_MAGIC; r.sequence=1U; r.state=BCR_PENDING; r.image_version=version; r.transaction_length=length; r.target_address=target; r.commit_marker=0xFFFFFFFFUL;
    bcr=fota_bcr_load(&old);if(bcr==FOTA_BCR_IO_ERROR)return false;
    if(bcr==FOTA_BCR_FOUND){
        if(old.state==BCR_PENDING&&old.image_version==version&&old.transaction_length==length&&old.target_address==target)return true;
        r.sequence=old.sequence+1U;r.rollback_floor=old.rollback_floor;
    }
    return fota_bcr_write_record(&r);
}

void fota_confirm_trial_process(void)
{
    bcr_record_t record;fota_bcr_result_t bcr;
    if(s_trial_checked||TICK_MS()<FOTA_TRIAL_HEALTHY_MS)return;
    if(!ext_flash_try_lock_now(EXT_FLASH_OWNER_OTA))return;
    bcr=fota_bcr_load(&record);
    if(bcr==FOTA_BCR_IO_ERROR){ext_flash_unlock(EXT_FLASH_OWNER_OTA);return;}
    if(bcr==FOTA_BCR_ABSENT||record.state!=BCR_TRIAL){
        s_trial_checked=true;
        ext_flash_unlock(EXT_FLASH_OWNER_OTA);
        return;
    }
    record.state=BCR_ACTIVE;
    record.boot_attempts=0U;
    record.sequence++;
    if(!fota_bcr_write_record(&record)){
        ext_flash_unlock(EXT_FLASH_OWNER_OTA);
        return;
    }
    ext_flash_unlock(EXT_FLASH_OWNER_OTA);
    s_trial_checked=true;
    NVIC_SystemReset();
}

static void release_resources(void)
{
    if(s_ota_lock){ext_flash_unlock(EXT_FLASH_OWNER_OTA);s_ota_lock=false;}
    if(s_workspace_lock){service_workspace_release(SERVICE_WORKSPACE_OWNER_OTA);s_workspace_lock=false;}
}

static void finish_check(void)
{
    s_state=FOTA_STATE_IDLE;s_next_check=TICK_MS()+FOTA_CHECK_INTERVAL_MS;
    release_resources();ec800m_tcp_close(FOTA_TCP_CH);
}

static void fail_download(void)
{
    s_state=FOTA_STATE_ERROR;
    release_resources();ec800m_tcp_close(FOTA_TCP_CH);
}

static void transport_failure(void)
{
    ec800m_tcp_close(FOTA_TCP_CH);s_connect_started=false;
    if(s_attempts>=FOTA_TRANSPORT_ATTEMPTS) {
        if(s_operation==FOTA_OP_CHECK)finish_check();else fail_download();
        return;
    }
    s_retry_due=TICK_MS()+(uint32_t)s_attempts*1000U;
    http_reset();
    if(s_operation==FOTA_OP_CHECK)s_state=FOTA_STATE_CHECK_CONNECTING;
    else {
        /* Discard any uncommitted partial sector, retaining durable progress. */
        s_received=0;s_crc=0xffffffffUL;
        if(!checkpoint_load()){fail_download();return;}
        schedule_tail_cleanup();
    }
}

static bool parse_http_u32(const char **cursor, uint32_t *value)
{
    const char *p = cursor != NULL ? *cursor : NULL;
    uint32_t result = 0U;
    uint8_t digits = 0U;
    if (p == NULL || value == NULL) return false;
    while (*p >= '0' && *p <= '9') {
        uint32_t digit = (uint32_t)(*p - '0');
        if (result > (UINT32_MAX - digit) / 10U) return false;
        result = result * 10U + digit;
        ++digits; ++p;
    }
    if (digits == 0U) return false;
    *cursor = p; *value = result;
    return true;
}

static bool parse_content_range(const char *line, uint32_t *first,
                                uint32_t *last, uint32_t *total)
{
    static const char prefix[] = "bytes ";
    const char *p;
    if (line == NULL || strncmp(line, prefix, sizeof(prefix) - 1U) != 0)
        return false;
    p = line + sizeof(prefix) - 1U;
    if (!parse_http_u32(&p, first) || *p++ != '-' ||
        !parse_http_u32(&p, last) || *p++ != '/' ||
        !parse_http_u32(&p, total)) return false;
    return *p == '\0';
}

static bool header_name(const char *a,const char *b)
{
    while(*a&&*b){char c=*a++;if(c>='A'&&c<='Z')c=(char)(c+'a'-'A');if(c!=*b++)return false;}
    return *a==0&&*b==0;
}

void fota_on_http_header(const char *header)
{
    char *cursor,*end;uint32_t length=0,first=0,last=0,total=0;
    bool have_length=false,have_range=false,have_type=false,have_etag=false;
    unsigned status;
    if(!header || !s_workspace_lock || (s_state!=FOTA_STATE_CHECKING && s_state!=FOTA_STATE_DOWNLOADING))return;
    s_http_error=FOTA_HTTP_INVALID;
    if(strlen(header)>FOTA_HTTP_LIMIT || !strstr(header,"\r\n\r\n"))return;
    if(header!=fota_http_header())memmove(fota_http_header(),header,strlen(header)+1U);
    cursor=fota_http_header();end=strstr(cursor,"\r\n");
    if(!end || end-cursor<12 || strncmp(cursor,"HTTP/1.1 ",9)!=0 ||
       cursor[9]<'0'||cursor[9]>'9'||cursor[10]<'0'||cursor[10]>'9'||
       cursor[11]<'0'||cursor[11]>'9'||(end-cursor>12&&cursor[12]!=' '))return;
    status=(unsigned)(cursor[9]-'0')*100U+(unsigned)(cursor[10]-'0')*10U+(unsigned)(cursor[11]-'0');
    if(status>=500U && status<=599U){s_http_error=FOTA_HTTP_TRANSPORT;return;}
    if(status!=200U && !(s_operation==FOTA_OP_DOWNLOAD && status==206U))return;
    cursor=end+2;
    while(*cursor!='\r') {
        char *colon,*value;const char *number;
        end=strstr(cursor,"\r\n");if(!end)return;*end=0;
        colon=strchr(cursor,':');if(!colon||colon==cursor)return;
        for(char *q=cursor;q<colon;++q)if(!((*q>='a'&&*q<='z')||(*q>='A'&&*q<='Z')||(*q>='0'&&*q<='9')||*q=='-'))return;
        *colon=0;value=colon+1;while(*value==' '||*value=='\t')++value;
        for(char *q=value;*q;++q)if(((uint8_t)*q<0x20U&&*q!='\t')||(uint8_t)*q>=0x7fU)return;
        char *tail=end;while(tail>value&&(tail[-1]==' '||tail[-1]=='\t'))*--tail=0;
        if(header_name(cursor,"content-length")) {
            number=value;if(have_length || !parse_http_u32(&number,&length)||*number)return;have_length=true;
        } else if(header_name(cursor,"transfer-encoding") || header_name(cursor,"content-encoding"))return;
        else if(header_name(cursor,"content-type")) {
            if(have_type)return;
            if(s_operation==FOTA_OP_CHECK && (strncmp(value,"application/json",16)!=0 ||
               (value[16]!=0&&value[16]!=';')))return;
            have_type=true;
        } else if(header_name(cursor,"content-range")) {
            if(have_range||!parse_content_range(value,&first,&last,&total))return;
            have_range=true;
        } else if(header_name(cursor,"etag")) {
            if(have_etag || strlen(value)>=sizeof s_etag)return;
            if(s_received&&s_etag[0]&&strcmp(value,s_etag)!=0)return;
            strcpy(s_etag,value);have_etag=true;
        }
        cursor=end+2;
    }
    if(!have_length || !length)return;
    if(s_operation==FOTA_OP_CHECK) {
        if(!have_type || have_range || length>FOTA_HTTP_LIMIT)return;
        s_check_length=(uint16_t)length;
    } else if(s_received && status==200U) {
        if(length!=s_expected || have_range)return;
        /* Process publishes a zero checkpoint before candidate-prefix erasure. */
        s_restart_zero=true;
    } else {
        if(length!=s_expected-s_received)return;
        if(status==206U) {
            if(!have_range || first!=s_received || last<first || total!=s_expected ||
               last>=total || last-first+1U!=length)return;
        } else if(s_received || have_range)return;
    }
    s_header_done=true;s_http_error=FOTA_HTTP_OK;
}

void fota_on_chunk(const uint8_t *data, uint16_t len, uint32_t offset)
{
    if(data && len && s_ota_lock && s_state==FOTA_STATE_VERIFYING) {s_http_error=FOTA_HTTP_INVALID;return;}
    if (s_state!=FOTA_STATE_DOWNLOADING || !data || !len || !s_ota_lock ||
        !s_header_done || s_restart_zero || s_http_error!=FOTA_HTTP_OK) return;
    if (offset>s_received || offset>s_expected || len>s_expected-offset) { s_http_error=FOTA_HTTP_INVALID; return; }
    if (offset<s_received) {
        uint8_t old[128]; uint32_t pos=0; while(pos<len){uint16_t n=(uint16_t)((len-pos)>sizeof old?sizeof old:(len-pos)); if(!ext_flash_read(EXT_FLASH_OWNER_OTA,FOTA_FLASH_ADDR+offset+pos,old,n)||memcmp(old,data+pos,n)!=0){s_http_error=FOTA_HTTP_INVALID;return;} pos+=n;}
        return;
    }
    while (len) {
        uint16_t n=(uint16_t)(FLASH_SECTOR_SIZE-s_received%FLASH_SECTOR_SIZE);
        if (n>len) n=len;
        if (!ext_flash_write_verified(EXT_FLASH_OWNER_OTA,FOTA_FLASH_ADDR+s_received,data,n)) { s_http_error=FOTA_HTTP_INVALID; return; }
        s_received+=n; s_crc=crc32_update(s_crc,data,n); data+=n; len=(uint16_t)(len-n);
        if (s_received%FLASH_SECTOR_SIZE==0U && !checkpoint_save()) { s_http_error=FOTA_HTTP_INVALID; return; }
    }
    if (s_expected && s_received==s_expected) s_state=FOTA_STATE_VERIFYING;
}

void fota_on_data(const uint8_t *data, uint16_t len) { fota_on_chunk(data,len,s_received); }

void fota_init(void)
{
    memset(s_url,0,sizeof s_url);memset(s_etag,0,sizeof s_etag);
    s_state=FOTA_STATE_IDLE;s_received=0;s_expected=0;s_ota_lock=false;
    s_workspace_lock=false;s_trial_checked=false;s_check_armed=true;
    s_next_check=TICK_MS();s_attempts=0;s_connect_started=false;s_signing_key_id=0U;
    s_authorization_committed=false;
    memset(s_package_sha256,0,sizeof s_package_sha256);memset(s_signature,0,sizeof s_signature);
    ec800m_register_ota_recv(fota_ec800m_rx);
}

bool fota_request_check(void) { s_check_armed=true;return true; }

int fota_start_request(const fota_request_t *req)
{
    bool from_check=s_workspace_lock && s_operation==FOTA_OP_CHECK;
    if (!req || !req->url || (s_state!=FOTA_STATE_IDLE && s_state!=FOTA_STATE_ERROR)) return -1;
    if (!req->expected_length || req->expected_length>FOTA_MAX_SIZE ||
        strlen(req->url)>=sizeof s_url || (req->etag && strlen(req->etag)>=sizeof s_etag)) return -1;
    if(!key_valid() || !same_origin(req->url))return -1;
    if(req->etag)for(const char *p=req->etag;*p;++p)if((uint8_t)*p<0x20U||(uint8_t)*p>=0x7fU)return -1;
    if (!parse_url(req->url,s_host,&s_port,s_path)) return -1;
    if(!req->package_sha256 || !req->signature || req->signing_key_id==0U)return -1;
    strncpy(s_url,req->url,sizeof s_url-1); s_url[sizeof s_url-1]=0; s_expected=req->expected_length; s_version=req->version; s_etag[0]=0; if(req->etag) strncpy(s_etag,req->etag,sizeof s_etag-1);
    memcpy(s_package_sha256,req->package_sha256,sizeof s_package_sha256);
    memcpy(s_signature,req->signature,sizeof s_signature);s_signing_key_id=req->signing_key_id;
    if (!s_workspace_lock && !service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_OTA)) return -1;
    s_workspace_lock=true;
    if(!from_check && !ec800m_ota_channel_prepare()){release_resources();return -1;}
    if (!s_ota_lock && !ext_flash_try_lock_now(EXT_FLASH_OWNER_OTA)) { release_resources();return -1; }
    s_ota_lock=true;s_operation=FOTA_OP_DOWNLOAD;s_attempts=0;s_retry_due=TICK_MS();
    s_authorization_committed=false;
    if(!from_check){s_check_armed=false;s_next_check=TICK_MS()+FOTA_CHECK_INTERVAL_MS;}
    if (!checkpoint_load()) {
        s_received=0; s_crc=0xFFFFFFFFUL;
        if (!checkpoint_save()) { fail_download(); return -1; }
    }
    schedule_tail_cleanup(); return 0;
}

int fota_start(const char *url)
{
    fota_request_t r={0}; r.url=url; r.expected_length=cfg_get()->fota_size; return fota_start_request(&r);
}

static void begin_check(void)
{
    char pid[12],phone[13],terminal[8],encoded[34],base_path[128];
    bcr_record_t record;int n;fota_bcr_result_t bcr;
    if(!key_valid() || !ec800m_is_ready() || !terminal_identity_sync(pid,phone,terminal))return;
    if(!parse_url(cfg_get()->fota_url,s_host,&s_port,base_path) || strchr(base_path,'?') ||
       !encode_query(pid,encoded,sizeof encoded)) {s_check_armed=false;s_next_check=TICK_MS()+FOTA_CHECK_INTERVAL_MS;return;}
    if(!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_OTA))return;
    s_workspace_lock=true;
    if(!ec800m_ota_channel_prepare()){release_resources();return;}
    if(!ext_flash_try_lock_now(EXT_FLASH_OWNER_OTA)){release_resources();return;}
    s_ota_lock=true;
    bcr=fota_bcr_load(&record);
    if(bcr==FOTA_BCR_IO_ERROR ||
       (bcr==FOTA_BCR_FOUND && (record.state==BCR_TRIAL || record.state==BCR_PENDING))) {
        release_resources();return;
    }
    size_t length=strlen(base_path);if(length && base_path[length-1]=='/')base_path[--length]=0;
    n=snprintf(s_path,sizeof s_path,"%s/api/device/updates/check?deviceId=%s&deviceModel=A300-406&currentVersionCode=%lu",
               base_path,encoded,(unsigned long)FW_VERSION_COUNTER);
    if(n<0 || (size_t)n>=sizeof s_path){s_check_armed=false;finish_check();return;}
    s_operation=FOTA_OP_CHECK;s_received=0;s_expected=0;s_etag[0]=0;
    s_check_armed=false;s_attempts=0;s_connect_started=false;s_retry_due=TICK_MS();
    http_reset();s_state=FOTA_STATE_CHECK_CONNECTING;
}

void fota_process(void)
{
    uint32_t now=TICK_MS();
    if(s_state==FOTA_STATE_IDLE || s_state==FOTA_STATE_ERROR) {
        if(s_check_armed || due(now,s_next_check))begin_check();
        return;
    }
    if(s_http_error!=FOTA_HTTP_OK) {
        if(s_http_error==FOTA_HTTP_TRANSPORT)transport_failure();
        else if(s_operation==FOTA_OP_CHECK)finish_check();else fail_download();
        return;
    }
    if(s_restart_zero) {
        s_received=0;s_crc=0xffffffffUL;
        if(!checkpoint_save()){fail_download();return;}
        ec800m_tcp_close(FOTA_TCP_CH);
        if(s_attempts>=FOTA_TRANSPORT_ATTEMPTS){fail_download();return;}
        s_retry_due=now+(uint32_t)s_attempts*1000U;schedule_tail_cleanup();return;
    }
    if (s_state==FOTA_STATE_PREPARING) {
        if (s_erase_offset<s_erase_end) {
            bool erased;
            IWDG_ReloadKey();
            erased=ext_flash_erase(EXT_FLASH_OWNER_OTA,FOTA_FLASH_ADDR+s_erase_offset,FLASH_SECTOR_SIZE);
            IWDG_ReloadKey();
            if(!erased){fail_download();return;}
            s_erase_offset+=FLASH_SECTOR_SIZE; return;
        }
        if (s_received==s_expected) { s_state=FOTA_STATE_VERIFYING; return; }
        s_state=FOTA_STATE_CONNECTING;return;
    }
    if(s_state==FOTA_STATE_CONNECTING || s_state==FOTA_STATE_CHECK_CONNECTING) {
        if(!s_connect_started) {
            if(!due(now,s_retry_due))return;
            ++s_attempts;s_connect_started=true;s_deadline=now+FOTA_CONNECT_TIMEOUT_MS;
            if(ec800m_tcp_open(FOTA_TCP_CH,s_host,s_port)!=0)transport_failure();
            return;
        }
        if(due(now,s_deadline) || ec800m_tcp_state(FOTA_TCP_CH)==TCP_STATE_ERROR ||
           ec800m_tcp_state(FOTA_TCP_CH)==TCP_STATE_CLOSED){transport_failure();return;}
        if(ec800m_tcp_state(FOTA_TCP_CH)!=TCP_STATE_OPEN)return;
        http_reset();s_deadline=now+FOTA_RX_TIMEOUT_MS;
        s_state=s_operation==FOTA_OP_CHECK?FOTA_STATE_CHECKING:FOTA_STATE_DOWNLOADING;
        if(!send_request())transport_failure();
        return;
    }
    if(s_state==FOTA_STATE_CHECKING && s_body_complete) {
        fota_check_response_t response;
        if(!fota_check_parse(fota_http_header(),s_http_body_len,&response) || !response.update_available ||
           response.version_code<=FW_VERSION_COUNTER || !response.size || response.size>FOTA_MAX_SIZE ||
           !same_origin(response.download_url)) {finish_check();return;}
        fota_request_t request={response.download_url,response.size,NULL,response.version_code,
                                response.package_sha256,response.signature,response.signing_key_id};
        s_next_check=now+FOTA_CHECK_INTERVAL_MS;
        ec800m_tcp_close(FOTA_TCP_CH);s_state=FOTA_STATE_IDLE;
        if(fota_start_request(&request)!=0)fail_download();
        return;
    }
    if((s_state==FOTA_STATE_CHECKING || s_state==FOTA_STATE_DOWNLOADING) &&
       (due(now,s_deadline) || ec800m_tcp_state(FOTA_TCP_CH)==TCP_STATE_CLOSED ||
        ec800m_tcp_state(FOTA_TCP_CH)==TCP_STATE_ERROR)) {transport_failure();return;}
    if (s_state==FOTA_STATE_VERIFYING) {
        fota_package_header_t m;fota_authorization_t authorization;
        if (s_received!=s_expected || s_received<sizeof m ||
            !ext_flash_read(EXT_FLASH_OWNER_OTA,FOTA_FLASH_ADDR,&m,sizeof m) ||
            m.body_size!=s_received-sizeof m || (s_version && m.version!=s_version)) {
            fail_download(); return;
        }
        if (!s_authorization_committed) {
            if (!fota_verify_manifest(&m,sizeof m)) { fail_download(); return; }
            memset(&authorization,0,sizeof authorization);
            authorization.package_length=s_expected;authorization.package_version=m.version;
            authorization.target_address=APP_FLASH_BASE;authorization.package_crc32=m.body_crc32;
            authorization.signing_key_id=s_signing_key_id;
            memcpy(authorization.package_sha256,s_package_sha256,sizeof authorization.package_sha256);
            memcpy(authorization.signature,s_signature,sizeof authorization.signature);
            if(!fota_authorization_commit(&authorization)) { fail_download(); return; }
            s_authorization_committed=true;
            return;
        }
        if(!fota_bcr_commit_pending(m.version,m.body_size,APP_FLASH_BASE)) { fail_download(); return; }
        release_resources();ec800m_tcp_close(FOTA_TCP_CH);
        IWDG_ReloadKey();NVIC_SystemReset();
    }
}

void fota_cancel(void) { release_resources();ec800m_tcp_close(FOTA_TCP_CH);s_state=FOTA_STATE_IDLE;s_check_armed=false;s_next_check=TICK_MS()+FOTA_CHECK_INTERVAL_MS; }
void fota_apply(void) { if(s_state==FOTA_STATE_READY){IWDG_ReloadKey();NVIC_SystemReset();} }
fota_state_t fota_get_state(void) { return s_state; }
uint32_t fota_get_progress(void) { return s_received; }
void fota_get_status(fota_status_t *out) { if(!out)return; memset(out,0,sizeof *out); out->state=s_state; out->offset=s_received; out->expected_length=s_expected; out->crc32=~s_crc; out->resumable=(s_received!=0); strncpy(out->url,s_url,sizeof out->url-1); strncpy(out->etag,s_etag,sizeof out->etag-1); }
