#include "fota.h"
#include "crc32.h"
#include "ec800m.h"
#include "ext_flash_store.h"
#include "flash_config.h"
#include "debug_uart.h"
#include "hw_init.h"
#include "config.h"
#include "firmware_signature.h"
#include "n32l40x.h"
#include "boot_contract.h"
#include "firmware_layout.h"
#include "service_workspace.h"
#include "../bootloader/include/image_manifest.h"
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>

#ifndef EC800M_H
typedef void (*ec800m_recv_cb_t)(uint8_t, const uint8_t *, uint16_t);
#endif

#define FOTA_TCP_CH EC800M_CH_OTA
#define FOTA_CHECKPOINT_ADDR (EXT_FLASH_RESUME_ADDR + 0x2000UL)
#define FOTA_CHECKPOINT_SECTOR (FOTA_CHECKPOINT_ADDR & ~(FLASH_SECTOR_SIZE - 1UL))
#define FOTA_RX_TIMEOUT_MS 60000UL
#define FOTA_CHECKPOINT_INTERVAL 4096UL
#define FOTA_TRIAL_HEALTHY_MS 30000UL
typedef struct __attribute__((packed)) {
    uint32_t magic, sequence, offset, expected_length, crc32, url_crc, etag_crc;
    uint32_t version, hash_bytes, commit_marker;
    char url[128], etag[40];
    uint8_t hash_state[96];
} fota_checkpoint_t;

static fota_state_t s_state = FOTA_STATE_IDLE;
static uint32_t s_expected, s_received, s_crc = 0xFFFFFFFFUL, s_last_rx, s_last_checkpoint;
static uint32_t s_version;
static char s_url[128], s_etag[40], s_host[CFG_IP_LEN], s_path[124];
static uint16_t s_port;
static bool s_header_done, s_ota_lock, s_resume_response;
static bool s_trial_checked;
static uint8_t s_http_header_len;

static char *fota_http_header(void)
{
    return (char *)service_workspace_buffer(NULL);
}

/* Host/unit-test builds may provide only the legacy EC800M surface. */
__attribute__((weak)) void ec800m_register_ota_recv(ec800m_recv_cb_t cb) { (void)cb; }

static uint32_t identity_crc(const char *s) { return s ? crc32_compute(s,(uint32_t)strlen(s)) : 0U; }

typedef struct { uint32_t h[8]; uint64_t bits; uint8_t block[64], used; } fota_sha256_t;
static uint32_t fota_rotr(uint32_t x,uint8_t n){return (x>>n)|(x<<(32U-n));}
static void fota_sha_block(fota_sha256_t *c,const uint8_t *p){
    static const uint32_t k[64]={0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c6ff3,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a8a,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x27b70db3,0x3c6ef372,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
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
static void fota_put_be32(uint8_t *out,uint32_t value){out[0]=(uint8_t)(value>>24);out[1]=(uint8_t)(value>>16);out[2]=(uint8_t)(value>>8);out[3]=(uint8_t)value;}
static void fota_signature_digest(const image_manifest_t *m,uint8_t out[32]){uint8_t canonical[56];fota_sha256_t sha;fota_put_be32(canonical,m->magic);fota_put_be32(canonical+4,m->product_id);fota_put_be32(canonical+8,m->hardware_id);fota_put_be32(canonical+12,m->target_address);fota_put_be32(canonical+16,m->image_length);fota_put_be32(canonical+20,m->version_counter);memcpy(canonical+24,m->sha256,32);fota_sha_init(&sha);fota_sha_update(&sha,canonical,sizeof canonical);fota_sha_final(&sha,out);}

static bool parse_url(const char *url, char *host, uint16_t *port, char *path)
{
    const char *p=url, *slash, *colon; uint32_t n;
    if (!url || !host || !port || !path) return false;
    if (!strncmp(p,"http://",7)) p += 7;
    slash=strchr(p,'/'); colon=strchr(p,':');
    if (colon && (!slash || colon<slash)) { n=(uint32_t)(colon-p); if (n>=CFG_IP_LEN) return false; memcpy(host,p,n); host[n]=0; *port=(uint16_t)atoi(colon+1); }
    else { n=slash?(uint32_t)(slash-p):(uint32_t)strlen(p); if (n>=CFG_IP_LEN) return false; memcpy(host,p,n); host[n]=0; *port=80; }
    if (!host[0]) return false;
    strncpy(path,slash?slash:"/",123); path[123]=0; return true;
}

static void fota_ec800m_rx(uint8_t ch, const uint8_t *data, uint16_t len)
{
    (void)ch;
    /* HTTP headers and body can arrive in separate QIRD reads. */
    if (!s_header_done) {
        const uint8_t *mark = 0;
        for (uint16_t i=0; i+3<len; ++i)
            if (data[i]=='\r' && data[i+1]=='\n' && data[i+2]=='\r' && data[i+3]=='\n') { mark=data+i+4; break; }
        if (!mark) {
            uint16_t n=(uint16_t)(SERVICE_WORKSPACE_CAPACITY-1U-s_http_header_len); if(n>len)n=len; if(n>255U-s_http_header_len)n=255U-s_http_header_len;
            memcpy(fota_http_header()+s_http_header_len,data,n); s_http_header_len=(uint8_t)(s_http_header_len+n); fota_http_header()[s_http_header_len]=0;
            fota_on_http_header(fota_http_header()); return;
        }
        uint16_t prefix=(uint16_t)(mark-data); uint16_t room=(uint16_t)(SERVICE_WORKSPACE_CAPACITY-1U-s_http_header_len); if(prefix>room)prefix=room; if(prefix>255U-s_http_header_len)prefix=255U-s_http_header_len; memcpy(fota_http_header()+s_http_header_len,data,prefix); s_http_header_len=(uint8_t)(s_http_header_len+prefix); fota_http_header()[s_http_header_len]=0; fota_on_http_header(fota_http_header()); s_http_header_len=0; fota_http_header()[0]=0; s_header_done=true;
        fota_on_chunk(mark,(uint16_t)(len-(mark-data)),s_received); return;
    }
    fota_on_chunk(data,len,s_received);
}

static void send_request(void)
{
    char req[320];
    if (s_received) snprintf(req,sizeof req,"GET %s HTTP/1.1\r\nHost: %s\r\nRange: bytes=%lu-\r\nConnection: close\r\n%s%s\r\n",s_path,s_host,(unsigned long)s_received,s_etag[0]?"If-Range: ":"",s_etag[0]?s_etag:"");
    else snprintf(req,sizeof req,"GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n",s_path,s_host);
    (void)ec800m_tcp_send(FOTA_TCP_CH,(const uint8_t *)req,(uint16_t)strlen(req));
}

static bool checkpoint_valid(const fota_checkpoint_t *c)
{
    fota_checkpoint_t x;
    if (!c || c->magic!=FOTA_RESUME_MAGIC || c->commit_marker!=BCR_COMMIT_MARKER || c->offset>FOTA_MAX_SIZE) return false;
    x=*c; x.commit_marker=0xFFFFFFFFUL; x.crc32=0U;
    return crc32_compute(&x,(uint32_t)offsetof(fota_checkpoint_t,crc32))==c->crc32;
}
static bool checkpoint_load(void)
{
    fota_checkpoint_t c;
    if (!s_ota_lock || !ext_flash_read(EXT_FLASH_OWNER_OTA,FOTA_CHECKPOINT_ADDR,&c,sizeof c) || !checkpoint_valid(&c)) return false;
    if (c.url_crc!=identity_crc(s_url) || (s_etag[0] && c.etag_crc!=identity_crc(s_etag))) return false;
    s_received=c.offset; s_expected=c.expected_length; s_version=c.version; s_crc=c.hash_bytes ? c.hash_bytes : 0xFFFFFFFFUL;
    strncpy(s_etag,c.etag,sizeof s_etag-1); s_etag[sizeof s_etag-1]=0; return true;
}
static bool checkpoint_save(void)
{
    fota_checkpoint_t c; memset(&c,0,sizeof c); c.magic=FOTA_RESUME_MAGIC; c.sequence=s_received; c.offset=s_received; c.expected_length=s_expected; c.url_crc=identity_crc(s_url); c.etag_crc=identity_crc(s_etag); c.version=s_version; c.hash_bytes=s_crc; c.commit_marker=0xFFFFFFFFUL; strncpy(c.url,s_url,sizeof c.url-1); strncpy(c.etag,s_etag,sizeof c.etag-1); c.crc32=crc32_compute(&c,(uint32_t)offsetof(fota_checkpoint_t,crc32));
    if (!ext_flash_erase(EXT_FLASH_OWNER_OTA,FOTA_CHECKPOINT_SECTOR,FLASH_SECTOR_SIZE)) return false;
    c.commit_marker=BCR_COMMIT_MARKER;
    return ext_flash_write_verified(EXT_FLASH_OWNER_OTA,FOTA_CHECKPOINT_ADDR,&c,sizeof c);
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

static bool fota_bcr_load(bcr_record_t *out)
{
    bcr_record_t a,b; bool va,vb;
    if(!out)return false;
    va=ext_flash_read(EXT_FLASH_OWNER_OTA,BCR_SLOT_A_ADDR,&a,sizeof a)&&fota_bcr_valid(&a);
    vb=ext_flash_read(EXT_FLASH_OWNER_OTA,BCR_SLOT_B_ADDR,&b,sizeof b)&&fota_bcr_valid(&b);
    if(!va&&!vb)return false;
    *out=(!vb||(va&&fota_sequence_newer(a.sequence,b.sequence)))?a:b;
    return true;
}

static bool fota_bcr_write_record(const bcr_record_t *record)
{
    bcr_record_t r=*record,check; uint32_t addr=(r.sequence&1U)?BCR_SLOT_B_ADDR:BCR_SLOT_A_ADDR;
    r.magic=BCR_MAGIC;r.commit_marker=0xFFFFFFFFUL;r.crc32=0U;
    r.crc32=crc32_compute(&r,(uint32_t)offsetof(bcr_record_t,crc32));
    if(!ext_flash_erase(EXT_FLASH_OWNER_OTA,addr,FLASH_SECTOR_SIZE)||
       !ext_flash_write_verified(EXT_FLASH_OWNER_OTA,addr,&r,(uint32_t)offsetof(bcr_record_t,commit_marker)))return false;
    r.commit_marker=BCR_COMMIT_MARKER;
    if(!ext_flash_write_verified(EXT_FLASH_OWNER_OTA,addr+offsetof(bcr_record_t,commit_marker),&r.commit_marker,sizeof r.commit_marker)||
       !ext_flash_read(EXT_FLASH_OWNER_OTA,addr,&check,sizeof check))return false;
    return fota_bcr_valid(&check)&&memcmp(&check,&r,sizeof r)==0;
}

bool fota_verify_manifest(const void *manifest, uint32_t length)
{
    const image_manifest_t *m=(const image_manifest_t *)manifest; image_manifest_t x; fota_sha256_t sha; uint8_t digest[32], signature_digest[32], buf[256]; uint32_t left,addr;
    bcr_record_t current; uint32_t floor=0U;
    if (!m || length<sizeof *m || m->magic!=IMAGE_MANIFEST_MAGIC || m->product_id!=fota_product_id() || m->hardware_id!=fota_hardware_id() || m->target_address!=APP_FLASH_BASE || m->version_counter==0U || m->image_length==0U || m->image_length>APP_FLASH_SIZE || m->image_length>FOTA_MAX_SIZE-sizeof *m) return false;
    if(fota_bcr_load(&current))floor=current.rollback_floor;
    if(m->version_counter<floor)return false;
    x=*m; x.crc32=0U; if (crc32_compute(&x,(uint32_t)offsetof(image_manifest_t,crc32))!=m->crc32) return false;
    fota_sha_init(&sha); left=m->image_length; addr=FOTA_FLASH_ADDR+sizeof *m;
    while(left){uint32_t n=left>sizeof buf?sizeof buf:left; if(!ext_flash_read(EXT_FLASH_OWNER_OTA,addr,buf,n))return false; fota_sha_update(&sha,buf,n); addr+=n; left-=n;}
    fota_sha_final(&sha,digest);
    if (memcmp(digest,m->sha256,sizeof digest)!=0) return false;
    fota_signature_digest(m,signature_digest);
    return firmware_signature_verify(signature_digest,m->ecdsa_signature);
}

bool fota_bcr_commit_pending(uint32_t version, uint32_t length, uint32_t target)
{
    bcr_record_t r, old; bool have_old=false;
    memset(&r,0,sizeof r); r.magic=BCR_MAGIC; r.sequence=1U; r.state=BCR_PENDING; r.image_version=version; r.transaction_length=length; r.target_address=target; r.commit_marker=0xFFFFFFFFUL;
    have_old=fota_bcr_load(&old);
    if(have_old){
        if(old.state==BCR_PENDING&&old.image_version==version&&old.transaction_length==length&&old.target_address==target)return true;
        r.sequence=old.sequence+1U;r.rollback_floor=old.rollback_floor;
    }
    return fota_bcr_write_record(&r);
}

void fota_confirm_trial_process(void)
{
    bcr_record_t record;
    if(s_trial_checked||TICK_MS()<FOTA_TRIAL_HEALTHY_MS)return;
    if(!ext_flash_try_lock_now(EXT_FLASH_OWNER_OTA))return;
    if(!fota_bcr_load(&record)||record.state!=BCR_TRIAL){
        s_trial_checked=true;
        ext_flash_unlock(EXT_FLASH_OWNER_OTA);
        return;
    }
    record.state=BCR_ACTIVE;
    record.boot_attempts=0U;
    record.rollback_floor=record.image_version;
    record.sequence++;
    if(!fota_bcr_write_record(&record)){
        ext_flash_unlock(EXT_FLASH_OWNER_OTA);
        return;
    }
    ext_flash_unlock(EXT_FLASH_OWNER_OTA);
    s_trial_checked=true;
    NVIC_SystemReset();
}

static void fail_download(void) { s_state=FOTA_STATE_ERROR; if (s_ota_lock) { ext_flash_unlock(EXT_FLASH_OWNER_OTA); s_ota_lock=false; } service_workspace_release(SERVICE_WORKSPACE_OWNER_OTA); }

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
    static const char prefix[] = "Content-Range: bytes ";
    const char *p;
    if (line == NULL || strncmp(line, prefix, sizeof(prefix) - 1U) != 0)
        return false;
    p = line + sizeof(prefix) - 1U;
    if (!parse_http_u32(&p, first) || *p++ != '-' ||
        !parse_http_u32(&p, last) || *p++ != '/' ||
        !parse_http_u32(&p, total)) return false;
    return *p == '\r' || *p == '\n' || *p == '\0';
}

void fota_on_http_header(const char *header)
{
    const char *p; unsigned long n;
    if (!header) return;
    p=strstr(header,"Content-Length:"); if (p) { n=strtoul(p+15,0,10); if (n==0 || n>FOTA_MAX_SIZE) { fail_download(); return; } if (!s_received && s_expected && s_expected!=n) { fail_download(); return; } if (!s_received || !strstr(header,"Content-Range:")) s_expected=(uint32_t)n; }
    p=strstr(header,"ETag:"); if (p) { char incoming[40]; p+=5; while (*p==' '||*p=='\t') p++; strncpy(incoming,p,sizeof incoming-1); incoming[sizeof incoming-1]=0; char *e=strpbrk(incoming,"\r\n"); if(e)*e=0; if (s_received && s_etag[0] && strcmp(s_etag,incoming)!=0) { fail_download(); return; } strncpy(s_etag,incoming,sizeof s_etag-1); s_etag[sizeof s_etag-1]=0; }
    p=strstr(header,"Content-Range:"); if (p) { uint32_t first,last,total; if (!parse_content_range(p,&first,&last,&total) || (!s_received && first!=0U) || (s_received && first!=s_received) || last<first || total>FOTA_MAX_SIZE) { fail_download(); return; } s_expected=total; s_resume_response=true; }
    if (s_received && !s_resume_response && !strstr(header,"HTTP/1.1 200")) { fail_download(); return; }
    if (s_received && strstr(header,"HTTP/1.1 206") == NULL) { if (strstr(header,"HTTP/1.1 200")) { if (!ext_flash_erase(EXT_FLASH_OWNER_OTA,FOTA_FLASH_ADDR,FOTA_MAX_SIZE)) { fail_download(); return; } s_received=0; s_crc=0xFFFFFFFFUL; s_resume_response=false; } else { fail_download(); return; } }
    (void)checkpoint_save();
}

void fota_on_chunk(const uint8_t *data, uint16_t len, uint32_t offset)
{
    if (s_state!=FOTA_STATE_DOWNLOADING || !data || !len || !s_ota_lock) return;
    if (offset>s_received || offset+len>FOTA_MAX_SIZE) { fail_download(); return; }
    if (offset<s_received) {
        uint8_t old[128]; uint32_t pos=0; while(pos<len){uint16_t n=(uint16_t)((len-pos)>sizeof old?sizeof old:(len-pos)); if(!ext_flash_read(EXT_FLASH_OWNER_OTA,FOTA_FLASH_ADDR+offset+pos,old,n)||memcmp(old,data+pos,n)!=0){fail_download();return;} pos+=n;}
        return;
    }
    if (!ext_flash_write_verified(EXT_FLASH_OWNER_OTA,FOTA_FLASH_ADDR+offset,data,len)) { fail_download(); return; }
    s_received += len; s_crc=crc32_update(s_crc,data,len); s_last_rx=TICK_MS();
    if (s_received-s_last_checkpoint>=FOTA_CHECKPOINT_INTERVAL || (s_expected && s_received>=s_expected)) { if (!checkpoint_save()) { fail_download(); return; } s_last_checkpoint=s_received; }
    if (s_expected && s_received==s_expected) s_state=FOTA_STATE_VERIFYING;
}

void fota_on_data(const uint8_t *data, uint16_t len) { fota_on_chunk(data,len,s_received); }

void fota_init(void)
{
    memset(s_url,0,sizeof s_url); memset(s_etag,0,sizeof s_etag); s_http_header_len=0; fota_http_header()[0]=0; s_resume_response=false; s_state=FOTA_STATE_IDLE; s_received=0; s_expected=0; s_ota_lock=false; s_trial_checked=false;
    ec800m_register_ota_recv(fota_ec800m_rx);
}

int fota_start_request(const fota_request_t *req)
{
    if (!req || !req->url || (s_state!=FOTA_STATE_IDLE && s_state!=FOTA_STATE_ERROR)) return -1;
    if (!parse_url(req->url,s_host,&s_port,s_path)) return -1;
    strncpy(s_url,req->url,sizeof s_url-1); s_url[sizeof s_url-1]=0; s_expected=req->expected_length; s_version=req->version; s_etag[0]=0; if(req->etag) strncpy(s_etag,req->etag,sizeof s_etag-1);
    if (s_expected>FOTA_MAX_SIZE) return -1;
    if (!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_OTA)) { s_state=FOTA_STATE_ERROR; return -1; }
    if (!ext_flash_try_lock(EXT_FLASH_OWNER_OTA)) { service_workspace_release(SERVICE_WORKSPACE_OWNER_OTA); s_state=FOTA_STATE_ERROR; return -1; } s_ota_lock=true;
    if (!checkpoint_load()) { s_received=0; s_crc=0xFFFFFFFFUL; if (!ext_flash_erase(EXT_FLASH_OWNER_OTA,FOTA_FLASH_ADDR,FOTA_MAX_SIZE)) { fail_download(); return -1; } (void)checkpoint_save(); }
    s_header_done=false; s_http_header_len=0; fota_http_header()[0]=0; s_resume_response=false; s_last_rx=TICK_MS(); s_last_checkpoint=s_received; s_state=FOTA_STATE_CONNECTING;
    if (ec800m_tcp_open(FOTA_TCP_CH,s_host,s_port)!=0) { fail_download(); return -1; }
    send_request(); s_state=FOTA_STATE_DOWNLOADING; return 0;
}

int fota_start(const char *url)
{
    fota_request_t r; r.url=url; r.expected_length=cfg_get()->fota_size; r.etag=0; r.version=0; return fota_start_request(&r);
}

void fota_process(void)
{
    #ifdef EC800M_H
    if (s_state==FOTA_STATE_DOWNLOADING && ec800m_tcp_state(FOTA_TCP_CH)==TCP_STATE_CLOSED) {
        if (ec800m_tcp_open(FOTA_TCP_CH,s_host,s_port)==0) { send_request(); s_last_rx=TICK_MS(); }
        else { fail_download(); return; }
    }
    #endif
    if (s_state==FOTA_STATE_DOWNLOADING && (uint32_t)(TICK_MS()-s_last_rx)>FOTA_RX_TIMEOUT_MS) { fail_download(); return; }
    if (s_state==FOTA_STATE_VERIFYING) {
        image_manifest_t m;
        if (s_received<sizeof m || !ext_flash_read(EXT_FLASH_OWNER_OTA,FOTA_FLASH_ADDR,&m,sizeof m) || m.image_length+sizeof m!=s_received || !fota_verify_manifest(&m,sizeof m) || !fota_bcr_commit_pending(m.version_counter,m.image_length,m.target_address)) { fail_download(); return; }
        s_state=FOTA_STATE_READY; if (s_ota_lock) { ext_flash_unlock(EXT_FLASH_OWNER_OTA); s_ota_lock=false; } service_workspace_release(SERVICE_WORKSPACE_OWNER_OTA);
    }
}

void fota_cancel(void) { if (s_ota_lock) { ext_flash_unlock(EXT_FLASH_OWNER_OTA); s_ota_lock=false; } service_workspace_release(SERVICE_WORKSPACE_OWNER_OTA); s_state=FOTA_STATE_IDLE; }
void fota_apply(void) { if (s_state==FOTA_STATE_READY) { delay_ms(50); NVIC_SystemReset(); } }
fota_state_t fota_get_state(void) { return s_state; }
uint32_t fota_get_progress(void) { return s_received; }
void fota_get_status(fota_status_t *out) { if(!out)return; memset(out,0,sizeof *out); out->state=s_state; out->offset=s_received; out->expected_length=s_expected; out->crc32=~s_crc; out->resumable=(s_received!=0); strncpy(out->url,s_url,sizeof out->url-1); strncpy(out->etag,s_etag,sizeof out->etag-1); }
