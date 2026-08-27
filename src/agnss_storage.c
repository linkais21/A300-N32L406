#include "agnss_storage.h"
#include "ext_flash_store.h"
#include "config.h"
#include <string.h>
#include <stddef.h>

#define AGNSS_MAGIC 0x41474E53UL
#define META_A (EXT_FLASH_AGNSS_META_ADDR)
#define META_B (EXT_FLASH_AGNSS_META_ADDR + FLASH_SECTOR_SIZE)

static uint8_t s_slot;
static uint32_t s_pos;
static bool s_active;
static uint8_t s_latest_slot;
static uint8_t s_buf[1024];

static uint32_t crc32_buf(const uint8_t *p, uint32_t n)
{
    uint32_t c=0xFFFFFFFFUL; while(n--){ c ^= *p++; for(int i=0;i<8;i++) c=(c>>1)^((c&1)?0xEDB88320UL:0); } return c^0xFFFFFFFFUL;
}

/* Small SHA-256 implementation, used incrementally only during commit. */
typedef struct { uint32_t h[8], n; uint8_t b[64]; uint32_t bl; } sha_t;
static uint32_t rr(uint32_t x,int n){return (x>>n)|(x<<(32-n));}
static void sh_init(sha_t*s){static const uint32_t h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};memcpy(s->h,h,sizeof h);s->n=s->bl=0;}
static void sh_blk(sha_t*s,const uint8_t*p){static const uint32_t k[64]={0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};uint32_t w[64],a,b,c,d,e,f,g,h,t1,t2;for(int i=0;i<16;i++)w[i]=((uint32_t)p[4*i]<<24)|((uint32_t)p[4*i+1]<<16)|((uint32_t)p[4*i+2]<<8)|p[4*i+3];for(int i=16;i<64;i++){uint32_t x=rr(w[i-15],7)^rr(w[i-15],18)^(w[i-15]>>3),y=rr(w[i-2],17)^rr(w[i-2],19)^(w[i-2]>>10);w[i]=w[i-16]+x+w[i-7]+y;}a=s->h[0];b=s->h[1];c=s->h[2];d=s->h[3];e=s->h[4];f=s->h[5];g=s->h[6];h=s->h[7];for(int i=0;i<64;i++){uint32_t S1=rr(e,6)^rr(e,11)^rr(e,25),ch=(e&f)^((~e)&g),S0=rr(a,2)^rr(a,13)^rr(a,22),maj=(a&b)^(a&c)^(b&c);t1=h+S1+ch+k[i]+w[i];t2=S0+maj;h=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;}s->h[0]+=a;s->h[1]+=b;s->h[2]+=c;s->h[3]+=d;s->h[4]+=e;s->h[5]+=f;s->h[6]+=g;s->h[7]+=h;}
static void sh_up(sha_t*s,const uint8_t*p,uint32_t n){s->n+=n;while(n){uint32_t k=64-s->bl;if(k>n)k=n;memcpy(s->b+s->bl,p,k);s->bl+=k;p+=k;n-=k;if(s->bl==64){sh_blk(s,s->b);s->bl=0;}}}
static void sh_fin(sha_t*s,uint8_t out[32]){uint64_t bits=(uint64_t)s->n*8;uint8_t z=0x80;sh_up(s,&z,1);z=0;while(s->bl!=56)sh_up(s,&z,1);uint8_t q[8];for(int i=0;i<8;i++)q[7-i]=(uint8_t)(bits>>(i*8));sh_up(s,q,8);for(int i=0;i<8;i++){out[4*i]=s->h[i]>>24;out[4*i+1]=s->h[i]>>16;out[4*i+2]=s->h[i]>>8;out[4*i+3]=s->h[i];}}

static uint32_t slot_base(uint8_t slot){return slot ? EXT_FLASH_AGNSS_SLOT_B_ADDR : EXT_FLASH_AGNSS_SLOT_A_ADDR;}
static uint32_t meta_addr(uint8_t slot){return slot ? META_B : META_A;}
static bool valid_meta(const agnss_meta_t*m){if(m->magic!=AGNSS_MAGIC||m->commit_marker!=AGNSS_COMMIT_MARKER||m->length>AGNSS_MAX_DATA||m->type==GNSS_TYPE_UNKNOWN)return false;return crc32_buf((const uint8_t*)m,(uint32_t)offsetof(agnss_meta_t,metadata_crc))==m->metadata_crc;}
static bool verify_payload(uint8_t slot,const agnss_meta_t*m){if(!ext_flash_try_lock(EXT_FLASH_OWNER_AGNSS))return false;sha_t sh;sh_init(&sh);uint32_t crc=0xFFFFFFFFUL,left=m->length,off=0;while(left){uint16_t n=(uint16_t)(left>sizeof s_buf?sizeof s_buf:left);if(!ext_flash_read(EXT_FLASH_OWNER_AGNSS,slot_base(slot)+off,s_buf,n)){ext_flash_unlock(EXT_FLASH_OWNER_AGNSS);return false;}for(uint16_t i=0;i<n;i++){crc^=s_buf[i];for(int j=0;j<8;j++)crc=(crc>>1)^((crc&1)?0xEDB88320UL:0);}sh_up(&sh,s_buf,n);off+=n;left-=n;}uint8_t h[32];sh_fin(&sh,h);ext_flash_unlock(EXT_FLASH_OWNER_AGNSS);return (crc^0xFFFFFFFFUL)==m->crc32&&memcmp(h,m->sha256,32)==0;}

bool agnss_storage_init(void){s_active=false;return true;}
bool agnss_storage_begin(uint8_t slot){if(slot>1||!ext_flash_try_lock(EXT_FLASH_OWNER_AGNSS))return false;s_slot=slot;s_pos=0;s_active=false;if(!ext_flash_erase(EXT_FLASH_OWNER_AGNSS,slot_base(slot),EXT_FLASH_AGNSS_SLOT_SIZE)){ext_flash_unlock(EXT_FLASH_OWNER_AGNSS);return false;}s_active=true;return true;}
bool agnss_storage_write(const void*d,uint16_t n){if(!s_active||!d||n>sizeof s_buf||s_pos+n>AGNSS_MAX_DATA){agnss_storage_abort();return false;}if(!ext_flash_write_verified(EXT_FLASH_OWNER_AGNSS,slot_base(s_slot)+s_pos,d,n)){agnss_storage_abort();return false;}s_pos+=n;return true;}
bool agnss_storage_commit(const agnss_meta_t *in){if(!s_active||!in||in->length!=s_pos){agnss_storage_abort();return false;}agnss_meta_t m=*in;m.magic=AGNSS_MAGIC;m.commit_marker=0xFFFFFFFFUL;memset(m.reserved,0,sizeof m.reserved);sha_t sh;sh_init(&sh);uint32_t left=m.length,off=0,crc=0xFFFFFFFFUL;while(left){uint16_t n=left>sizeof s_buf?sizeof s_buf:(uint16_t)left;if(!ext_flash_read(EXT_FLASH_OWNER_AGNSS,slot_base(s_slot)+off,s_buf,n))goto fail;for(uint16_t i=0;i<n;i++){crc^=s_buf[i];for(int j=0;j<8;j++)crc=(crc>>1)^((crc&1)?0xEDB88320UL:0);}sh_up(&sh,s_buf,n);off+=n;left-=n;}m.crc32=crc^0xFFFFFFFFUL;sh_fin(&sh,m.sha256);m.timestamp = m.timestamp ? m.timestamp : TICK_MS();m.metadata_crc=crc32_buf((const uint8_t*)&m,(uint32_t)offsetof(agnss_meta_t,metadata_crc));if(!ext_flash_erase(EXT_FLASH_OWNER_AGNSS,meta_addr(s_slot),FLASH_SECTOR_SIZE))goto fail;if(!ext_flash_write_verified(EXT_FLASH_OWNER_AGNSS,meta_addr(s_slot),&m,(uint32_t)offsetof(agnss_meta_t,commit_marker)))goto fail;if(!ext_flash_write_verified(EXT_FLASH_OWNER_AGNSS,meta_addr(s_slot)+offsetof(agnss_meta_t,commit_marker),&((uint32_t){AGNSS_COMMIT_MARKER}),4))goto fail;ext_flash_unlock(EXT_FLASH_OWNER_AGNSS);s_active=false;s_latest_slot=s_slot;return true;fail:agnss_storage_abort();return false;}
bool agnss_storage_get_latest(agnss_meta_t*out){if(!out)return false;agnss_meta_t a,b;bool la=ext_flash_try_lock(EXT_FLASH_OWNER_AGNSS);bool va=la&&ext_flash_read(EXT_FLASH_OWNER_AGNSS,META_A,&a,sizeof a)&&valid_meta(&a);if(la)ext_flash_unlock(EXT_FLASH_OWNER_AGNSS);bool lb=ext_flash_try_lock(EXT_FLASH_OWNER_AGNSS);bool vb=lb&&ext_flash_read(EXT_FLASH_OWNER_AGNSS,META_B,&b,sizeof b)&&valid_meta(&b);if(lb)ext_flash_unlock(EXT_FLASH_OWNER_AGNSS);if(va&&!verify_payload(0,&a))va=false;if(vb&&!verify_payload(1,&b))vb=false;if(!va&&!vb)return false;if(!vb||(va&&a.sequence>=b.sequence)){*out=a;s_latest_slot=0;}else {*out=b;s_latest_slot=1;}return true;}
uint32_t agnss_storage_data_base(const agnss_meta_t*m){(void)m;return EXT_FLASH_AGNSS_SLOT_A_ADDR + (s_latest_slot ? EXT_FLASH_AGNSS_SLOT_SIZE : 0u);}
bool agnss_storage_read(uint32_t off,void*buf,uint16_t n){agnss_meta_t m;if(!buf||off>AGNSS_MAX_DATA||n>AGNSS_MAX_DATA-off||!agnss_storage_get_latest(&m)||off>m.length||n>m.length-off||n>sizeof s_buf)return false;if(!ext_flash_try_lock(EXT_FLASH_OWNER_AGNSS))return false;bool ok=ext_flash_read(EXT_FLASH_OWNER_AGNSS,slot_base(s_latest_slot)+off,buf,n);ext_flash_unlock(EXT_FLASH_OWNER_AGNSS);return ok;}
void agnss_storage_abort(void){if(s_active){s_active=false;ext_flash_unlock(EXT_FLASH_OWNER_AGNSS);}}
