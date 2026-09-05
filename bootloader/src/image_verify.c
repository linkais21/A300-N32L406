#include "image_verify.h"
#include "bootloader_config.h"
#include "firmware_signature.h"
#include <stddef.h>
#include <string.h>

#define CANDIDATE_BASE 0x010000UL
#define CANDIDATE_LIMIT 0x080000UL

uint32_t image_crc32(const void *data, uint32_t length)
{
    const uint8_t *p = (const uint8_t *)data;
    uint32_t crc = 0xFFFFFFFFUL;
    while (length--) {
        crc ^= *p++;
        for (uint8_t bit = 0; bit < 8U; ++bit)
            crc = (crc >> 1) ^ (0xEDB88320UL & (uint32_t)-(int32_t)(crc & 1U));
    }
    return ~crc;
}

/* Small SHA-256 implementation keeps the bootloader independent of SDK crypto. */
typedef struct { uint32_t h[8]; uint64_t bits; uint8_t block[64], used; } sha256_ctx_t;
static uint32_t rotr(uint32_t x, uint8_t n) { return (x >> n) | (x << (32U - n)); }
static void sha256_block(sha256_ctx_t *c, const uint8_t *p)
{
    static const uint32_t k[64] = {
        0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
        0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
        0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
        0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
        0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
        0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
        0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
        0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
    uint32_t w[64], a,b,d,e,f,g,h,t1,t2;
    for (uint8_t i=0; i<16; ++i) w[i]=(uint32_t)p[i*4]<<24|(uint32_t)p[i*4+1]<<16|(uint32_t)p[i*4+2]<<8|p[i*4+3];
    for (uint8_t i=16; i<64; ++i) { uint32_t s0=rotr(w[i-15],7)^rotr(w[i-15],18)^(w[i-15]>>3); uint32_t s1=rotr(w[i-2],17)^rotr(w[i-2],19)^(w[i-2]>>10); w[i]=w[i-16]+s0+w[i-7]+s1; }
    a=c->h[0];b=c->h[1];d=c->h[3];e=c->h[4];f=c->h[5];g=c->h[6];h=c->h[7];
    uint32_t cc=c->h[2];
    for (uint8_t i=0; i<64; ++i) { uint32_t s1=rotr(e,6)^rotr(e,11)^rotr(e,25); uint32_t ch=(e&f)^((~e)&g); t1=h+s1+ch+k[i]+w[i]; uint32_t s0=rotr(a,2)^rotr(a,13)^rotr(a,22); uint32_t maj=(a&b)^(a&cc)^(b&cc); t2=s0+maj; h=g;g=f;f=e;e=d+t1;d=cc;cc=b;b=a;a=t1+t2; }
    c->h[0]+=a;c->h[1]+=b;c->h[2]+=cc;c->h[3]+=d;c->h[4]+=e;c->h[5]+=f;c->h[6]+=g;c->h[7]+=h;
}
static void sha256_init(sha256_ctx_t *c) { static const uint32_t h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19}; memcpy(c->h,h,sizeof h); c->bits=0;c->used=0; }
static void sha256_update(sha256_ctx_t *c,const uint8_t *p,uint32_t n) { c->bits += n*8U; while(n){ uint32_t room=64U-(uint32_t)c->used; uint8_t take=(uint8_t)((n < room)?n:room); memcpy(c->block+c->used,p,take); c->used += take;p+=take;n-=take; if(c->used==64){sha256_block(c,c->block);c->used=0;} } }
static void sha256_final(sha256_ctx_t *c,uint8_t out[32]) { uint8_t i; c->block[c->used++]=0x80; while(c->used!=56){if(c->used==64){sha256_block(c,c->block);c->used=0;} c->block[c->used++]=0;} for(i=0;i<8;++i)c->block[56+i]=(uint8_t)(c->bits>>(56-8*i)); sha256_block(c,c->block); for(i=0;i<8;++i){out[4*i]=(uint8_t)(c->h[i]>>24);out[4*i+1]=(uint8_t)(c->h[i]>>16);out[4*i+2]=(uint8_t)(c->h[i]>>8);out[4*i+3]=(uint8_t)c->h[i];} }

static void put_be32(uint8_t *out, uint32_t value)
{
    out[0]=(uint8_t)(value>>24); out[1]=(uint8_t)(value>>16);
    out[2]=(uint8_t)(value>>8); out[3]=(uint8_t)value;
}

void image_signature_digest(const image_manifest_t *manifest, uint8_t out[32])
{
    uint8_t canonical[56];
    sha256_ctx_t sha;
    if (!manifest || !out) return;
    put_be32(canonical,manifest->magic); put_be32(canonical+4,manifest->product_id);
    put_be32(canonical+8,manifest->hardware_id); put_be32(canonical+12,manifest->target_address);
    put_be32(canonical+16,manifest->image_length); put_be32(canonical+20,manifest->version_counter);
    memcpy(canonical+24,manifest->sha256,32);
    sha256_init(&sha); sha256_update(&sha,canonical,sizeof canonical); sha256_final(&sha,out);
}

image_verify_result_t verify_candidate(const image_manifest_t *m)
{
    uint8_t buf[256], digest[32], signature_digest[32];
    image_manifest_t copy;
    sha256_ctx_t sha;
    if (!m || m->magic != IMAGE_MANIFEST_MAGIC) return IMAGE_VERIFY_CRC;
    copy = *m; copy.crc32 = 0U;
    if (image_crc32(&copy, (uint32_t)offsetof(image_manifest_t, crc32)) != m->crc32) return IMAGE_VERIFY_CRC;
    if (m->target_address != APP_FLASH_BASE || m->target_address > APP_FLASH_END || m->image_length == 0U || m->image_length > (APP_FLASH_END - m->target_address)) return IMAGE_VERIFY_BOUNDS;
    if (m->image_length > (CANDIDATE_LIMIT - CANDIDATE_BASE - (uint32_t)sizeof(*m))) return IMAGE_VERIFY_BOUNDS;
    if (m->product_id != BOOTLOADER_PRODUCT_ID || m->hardware_id != BOOTLOADER_HARDWARE_ID) return IMAGE_VERIFY_ID;
    if (m->version_counter < boot_rollback_counter()) return IMAGE_VERIFY_ROLLBACK;
    if (!boot_ext_is_complete(CANDIDATE_BASE, (uint32_t)sizeof(*m) + m->image_length)) return IMAGE_VERIFY_INCOMPLETE;
    sha256_init(&sha);
    uint32_t left=m->image_length, address=CANDIDATE_BASE+(uint32_t)sizeof(*m);
    while(left){uint32_t n=left>sizeof(buf)?sizeof(buf):left; if(!boot_ext_read(address,buf,n)) return IMAGE_VERIFY_INCOMPLETE; sha256_update(&sha,buf,n); address+=n;left-=n;}
    sha256_final(&sha,digest);
    if (memcmp(digest,m->sha256,sizeof digest)!=0) return IMAGE_VERIFY_HASH;
    image_signature_digest(m,signature_digest);
    if (!firmware_signature_verify(signature_digest,m->ecdsa_signature)) return IMAGE_VERIFY_SIGNATURE;
    return IMAGE_VERIFY_OK;
}

bool verify_external_manifest(const image_manifest_t *m, uint32_t base)
{
    if (!m || m->magic != IMAGE_MANIFEST_MAGIC || m->product_id != BOOTLOADER_PRODUCT_ID || m->hardware_id != BOOTLOADER_HARDWARE_ID) return false;
    image_manifest_t copy = *m; uint32_t crc = m->crc32; copy.crc32 = 0U;
    if (image_crc32(&copy, (uint32_t)offsetof(image_manifest_t, crc32)) != crc) return false;
    uint32_t region_end = (base == 0x010000UL) ? 0x080000UL : (base == 0x080000UL || base == 0x0C0000UL) ? 0x100000UL : 0U;
    if (region_end == 0U || base > region_end || m->image_length > (region_end - base - sizeof(*m))) return false;
    if (m->image_length == 0U || m->image_length > APP_FLASH_MAX_SIZE || m->target_address < APP_FLASH_BASE || m->target_address > APP_FLASH_END || m->image_length > (APP_FLASH_END - m->target_address)) return false;
    if (m->version_counter < boot_rollback_counter()) return false;
    if (!boot_ext_is_complete(base, (uint32_t)sizeof(*m) + m->image_length)) return false;
    uint8_t buf[256], digest[32], signature_digest[32]; sha256_ctx_t sha; sha256_init(&sha);
    uint32_t left=m->image_length, address=base+(uint32_t)sizeof(*m);
    while (left) { uint32_t n=left>sizeof(buf)?sizeof(buf):left; if(!boot_ext_read(address,buf,n)) return false; sha256_update(&sha,buf,n); address+=n; left-=n; }
    sha256_final(&sha,digest);
    if (memcmp(digest,m->sha256,sizeof digest)!=0) return false;
    image_signature_digest(m,signature_digest);
    return firmware_signature_verify(signature_digest,m->ecdsa_signature);
}
