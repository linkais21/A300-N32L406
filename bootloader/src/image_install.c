#include "image_install.h"
#include "image_verify.h"
#include "bcr.h"
#include "bootloader_config.h"
#include <string.h>
#include <stddef.h>

#define CANDIDATE_BASE 0x010000UL
#define FACTORY_BASE   0x080000UL
#define FACTORY_PAYLOAD_BASE (FACTORY_BASE + FOTA_PACKAGE_HEADER_SIZE)

static bool copy_image(uint32_t source, uint32_t target, uint32_t length)
{
    uint8_t page[BOOTLOADER_COPY_CHUNK_SIZE], verify[BOOTLOADER_COPY_CHUNK_SIZE];
    /* Restore replaces the whole App region so a shorter verified image cannot
     * leave executable bytes from a previously failed image in its tail. */
    if (!boot_int_flash_erase(target, APP_FLASH_MAX_SIZE)) return false;
    for (uint32_t offset=0; offset<length; offset+=sizeof page) {
        uint32_t n = (length-offset > sizeof page) ? sizeof page : length-offset;
        if (!boot_ext_read(source+offset,page,n) || !boot_int_flash_program(target+offset,page,n) || !boot_int_flash_read(target+offset,verify,n) || memcmp(page,verify,n)!=0) return false;
        boot_watchdog_feed();
    }
    return true;
}

static bool select_newest_lkg(image_manifest_t *manifest,fota_authorization_t *auth,
                              uint32_t *base,bool promotion)
{
    image_manifest_t a,b;fota_authorization_t aa,ba;bool va,vb;
    va=boot_ext_read(LKG_SLOT_A_BASE,&a,sizeof a)&&boot_authorization_read_at(LKG_SLOT_A_AUTH_ADDR,&aa)&&(promotion?verify_external_manifest_for_promotion(&a,LKG_SLOT_A_BASE,LKG_SLOT_A_AUTH_ADDR):verify_external_manifest(&a,LKG_SLOT_A_BASE,LKG_SLOT_A_AUTH_ADDR));
    vb=boot_ext_read(LKG_SLOT_B_BASE,&b,sizeof b)&&boot_authorization_read_at(LKG_SLOT_B_AUTH_ADDR,&ba)&&(promotion?verify_external_manifest_for_promotion(&b,LKG_SLOT_B_BASE,LKG_SLOT_B_AUTH_ADDR):verify_external_manifest(&b,LKG_SLOT_B_BASE,LKG_SLOT_B_AUTH_ADDR));
    if(!va&&!vb)return false;
    if(vb&&(!va||(int32_t)(ba.sequence-aa.sequence)>0)){if(manifest)*manifest=b;if(auth)*auth=ba;if(base)*base=LKG_SLOT_B_BASE;}
    else {if(manifest)*manifest=a;if(auth)*auth=aa;if(base)*base=LKG_SLOT_A_BASE;}
    return true;
}

/* The App becomes ACTIVE before its first LKG promotion.  Keep the previous
 * rollback floor until a complete, verified LKG exists; the BCR commit is the
 * final transaction step that makes the new floor authoritative. */
static bool commit_lkg_floor(bcr_record_t *active, uint32_t version)
{
    bcr_record_t updated;
    if (!active || active->state != BCR_ACTIVE || version <= active->rollback_floor) return true;
    updated = *active;
    updated.rollback_floor = version;
    ++updated.sequence;
    if (!bcr_commit(&updated)) return false;
    *active = updated;
    return true;
}

static bool write_lkg_transaction(const image_manifest_t *manifest, bcr_record_t *active)
{
    uint8_t page[BOOTLOADER_COPY_CHUNK_SIZE],verify[BOOTLOADER_COPY_CHUNK_SIZE];image_manifest_t current,copied;fota_authorization_t auth,current_auth,check;uint32_t current_base,target,auth_addr,total,marker;
    if(!manifest||!active||manifest->body_size==0U||manifest->body_size>APP_FLASH_MAX_SIZE||!boot_authorization_load(&auth))return false;
    bool have_current=select_newest_lkg(&current,&current_auth,&current_base,true);
    if(have_current&&current.version==manifest->version&&memcmp(current_auth.package_sha256,auth.package_sha256,32)==0)return commit_lkg_floor(active,manifest->version);
    target=have_current?(current_base==LKG_SLOT_A_BASE?LKG_SLOT_B_BASE:LKG_SLOT_A_BASE):LKG_SLOT_B_BASE;
    auth_addr=target==LKG_SLOT_A_BASE?LKG_SLOT_A_AUTH_ADDR:LKG_SLOT_B_AUTH_ADDR;
    total=FOTA_PACKAGE_HEADER_SIZE+manifest->body_size;
    if(total>LKG_SLOT_SIZE||!boot_ext_erase(target,LKG_SLOT_SIZE))return false;
    for (uint32_t offset=0; offset<total; offset+=sizeof page) {
        uint32_t n=(total-offset>sizeof page)?sizeof page:total-offset;
        if (!boot_ext_read(CANDIDATE_BASE+offset,page,n) ||
            !boot_ext_write(target+offset,page,n) ||
            !boot_ext_read(target+offset,verify,n) || memcmp(page,verify,n)!=0) return false;
        boot_watchdog_feed();
    }
    auth.sequence=have_current?current_auth.sequence+1U:1U;auth.magic=FOTA_AUTH_MAGIC;auth.format_version=FOTA_AUTH_FORMAT;auth.record_length=sizeof auth;auth.commit_marker=0xFFFFFFFFUL;auth.crc32=0U;auth.crc32=image_crc32(&auth,(uint32_t)offsetof(fota_authorization_t,crc32));
    if(!boot_ext_erase(auth_addr,4096U)||!boot_ext_write(auth_addr,&auth,(uint32_t)offsetof(fota_authorization_t,commit_marker)))return false;
    marker=FOTA_AUTH_COMMIT_MARKER;if(!boot_ext_write(auth_addr+offsetof(fota_authorization_t,commit_marker),&marker,sizeof marker)||!boot_ext_read(auth_addr,&check,sizeof check))return false;
    auth.commit_marker=marker;
    if(memcmp(&auth,&check,sizeof auth)!=0||!boot_ext_read(target,&copied,sizeof copied)||!verify_external_manifest(&copied,target,auth_addr))return false;
    return commit_lkg_floor(active,manifest->version);
}

bool install_candidate(const image_manifest_t *manifest)
{
    bcr_record_t r;
    if (verify_candidate(manifest) != IMAGE_VERIFY_OK) return false;
    r=(bcr_record_t){.sequence=1U,.state=BCR_PENDING,.image_version=manifest->version,.transaction_offset=0U,.transaction_length=manifest->body_size,.target_address=APP_FLASH_BASE};
    bcr_record_t previous;
    bcr_load_result_t loaded = bcr_load(&previous);
    if (loaded == BCR_LOAD_IO_ERROR) return false;
    if (loaded == BCR_LOAD_FOUND) { r.sequence=previous.sequence+1U; r.rollback_floor=previous.rollback_floor; }
    if (!bcr_commit(&r)) return false;
    return install_resume(0U);
}

bool install_resume(uint32_t offset)
{
    uint32_t reported_bucket;
    bcr_record_t r; uint8_t page[BOOTLOADER_COPY_CHUNK_SIZE], verify[BOOTLOADER_COPY_CHUNK_SIZE];
    image_manifest_t m;
    if (bcr_load(&r) != BCR_LOAD_FOUND || r.state != BCR_PENDING || offset != r.transaction_offset ||
        !r.transaction_length || offset > r.transaction_length ||
        (r.transaction_offset != r.transaction_length &&
         (r.transaction_offset % BOOTLOADER_INTERNAL_PAGE_SIZE) != 0U) ||
        !boot_ext_read(CANDIDATE_BASE,&m,sizeof m) || verify_candidate(&m) != IMAGE_VERIFY_OK ||
        r.target_address != APP_FLASH_BASE || r.transaction_length != m.body_size ||
        r.image_version != m.version || r.target_address < APP_FLASH_BASE ||
        r.target_address > APP_FLASH_END || r.transaction_length > (APP_FLASH_END - r.target_address)) return false;
    reported_bucket = (r.transaction_offset * 10U) / r.transaction_length;
    if (r.transaction_offset < r.transaction_length)
        boot_install_progress(r.transaction_offset, r.transaction_length, false);
    while (r.transaction_offset < r.transaction_length) {
        uint32_t page_offset = r.transaction_offset;
        uint32_t page_length = r.transaction_length - page_offset;
        if (page_length > BOOTLOADER_INTERNAL_PAGE_SIZE) page_length = BOOTLOADER_INTERNAL_PAGE_SIZE;
        uint32_t page_end = page_offset + page_length;
        if ((r.target_address + page_offset) % BOOTLOADER_INTERNAL_PAGE_SIZE != 0U ||
            !boot_int_flash_erase(r.target_address + page_offset, BOOTLOADER_INTERNAL_PAGE_SIZE)) return false;
        for (uint32_t chunk_offset = 0U; chunk_offset < page_length; chunk_offset += sizeof page) {
            uint32_t n = page_length - chunk_offset;
            if (n > sizeof page) n = sizeof page;
            if (!boot_ext_read(CANDIDATE_BASE + FOTA_PACKAGE_HEADER_SIZE + page_offset + chunk_offset, page, n) ||
                !boot_int_flash_program(r.target_address + page_offset + chunk_offset, page, n) ||
                !boot_int_flash_read(r.target_address + page_offset + chunk_offset, verify, n) ||
                memcmp(page, verify, n) != 0) return false;
            boot_watchdog_feed();
        }
        for (uint32_t page_offset = 0U; page_offset < page_length; page_offset += sizeof page) {
            uint32_t n = page_length - page_offset;
            if (n > sizeof page) n = sizeof page;
            if (!boot_ext_read(CANDIDATE_BASE + FOTA_PACKAGE_HEADER_SIZE + r.transaction_offset + page_offset, page, n) ||
                !boot_int_flash_read(r.target_address + r.transaction_offset + page_offset, verify, n) ||
                memcmp(page, verify, n) != 0) return false;
            boot_watchdog_feed();
        }
        r.transaction_offset = page_end;
        ++r.sequence;
        if (!bcr_commit(&r)) return false;
        uint32_t bucket = (r.transaction_offset * 10U) / r.transaction_length;
        if (bucket > reported_bucket && r.transaction_offset < r.transaction_length) {
            reported_bucket = bucket;
            boot_install_progress(r.transaction_offset, r.transaction_length, false);
        }
        boot_watchdog_feed();
    }
    /* A durable offset proves a previous readback, not the current contents
     * after a brownout. Include the resumed prefix and the final-offset case
     * before making any internal image executable. Reuse the copy buffers. */
    for (uint32_t checked = 0U; checked < r.transaction_length; checked += sizeof page) {
        uint32_t n = r.transaction_length - checked;
        if (n > sizeof page) n = sizeof page;
        if (!boot_ext_read(CANDIDATE_BASE + FOTA_PACKAGE_HEADER_SIZE + checked, page, n) ||
            !boot_int_flash_read(r.target_address + checked, verify, n) ||
            memcmp(page, verify, n) != 0) return false;
        boot_watchdog_feed();
    }
    r.state=BCR_TRIAL; r.boot_attempts=0U; ++r.sequence;
    if (!bcr_commit(&r)) return false;
    boot_install_progress(r.transaction_length, r.transaction_length, true);
    return true;
}

bool bootloader_select_image(void)
{
    bcr_record_t r;
    bcr_load_result_t loaded = bcr_load(&r);
    if (loaded == BCR_LOAD_ABSENT) {
        /* SWD-only first programming writes internal Bootloader+App but cannot
         * provision external NOR BCR.  Boot a structurally valid internal App
         * once; OTA-created BCR records retain the normal rollback policy. */
        if (boot_app_vectors_valid(APP_FLASH_BASE)) boot_jump_to(APP_FLASH_BASE);
        return false;
    }
    if (loaded != BCR_LOAD_FOUND) return false;
    if (r.state == BCR_PENDING) {
        if (install_resume(r.transaction_offset)) boot_jump_to(APP_FLASH_BASE);
        else { r.state = BCR_ROLLBACK; r.boot_attempts = BOOTLOADER_TRIAL_LIMIT; ++r.sequence; if (bcr_commit(&r)) (void)bootloader_select_image(); }
        return false;
    }
    if (r.state == BCR_ACTIVE) {
        image_manifest_t m;
        if (boot_ext_read(CANDIDATE_BASE,&m,sizeof m) &&
            r.image_version == m.version &&
            r.transaction_length == m.body_size &&
            r.target_address == APP_FLASH_BASE &&
            verify_candidate(&m) == IMAGE_VERIFY_OK) {
            /* LKG preservation is best-effort. A valid internal App must still
             * boot when the optional external Flash is absent or unavailable. */
            (void)write_lkg_transaction(&m,&r);
        }
        if (!boot_app_vectors_valid(APP_FLASH_BASE)) {
            r.state = BCR_ROLLBACK;
            r.boot_attempts = BOOTLOADER_TRIAL_LIMIT;
            ++r.sequence;
            if (bcr_commit(&r)) (void)bootloader_select_image();
            return false;
        }
        boot_jump_to(APP_FLASH_BASE);
        return false;
    }
    if ((r.state == BCR_TRIAL || r.state == BCR_ROLLBACK) && r.boot_attempts >= BOOTLOADER_TRIAL_LIMIT) {
        image_manifest_t m;fota_authorization_t auth;uint32_t base;legacy_image_manifest_t legacy;
        if(select_newest_lkg(&m,&auth,&base,false)&&copy_image(base+FOTA_PACKAGE_HEADER_SIZE,APP_FLASH_BASE,m.body_size)){r.state=BCR_ACTIVE;r.image_version=m.version;r.rollback_floor=m.version;r.boot_attempts=0U;++r.sequence;if(bcr_commit(&r)){boot_jump_to(APP_FLASH_BASE);return false;}}
        if(verify_legacy_package(LKG_SLOT_A_BASE,0x100000UL,&legacy)&&copy_image(LKG_SLOT_A_BASE+sizeof legacy,APP_FLASH_BASE,legacy.image_length)){r.state=BCR_ACTIVE;r.image_version=legacy.version_counter;r.rollback_floor=legacy.version_counter;r.boot_attempts=0U;++r.sequence;if(bcr_commit(&r)){boot_jump_to(APP_FLASH_BASE);return false;}}
        if (boot_ext_read(FACTORY_BASE,&m,sizeof m) && verify_external_manifest(&m,FACTORY_BASE,FOTA_FACTORY_AUTH_ADDR) && copy_image(FACTORY_PAYLOAD_BASE,APP_FLASH_BASE,m.body_size)) { r.state=BCR_ACTIVE; r.image_version=m.version; r.rollback_floor=m.version; r.boot_attempts=0U; ++r.sequence; if (bcr_commit(&r)) { boot_jump_to(APP_FLASH_BASE); return false; } }
        if(verify_legacy_package(FACTORY_BASE,0x0C0000UL,&legacy)&&copy_image(FACTORY_BASE+sizeof legacy,APP_FLASH_BASE,legacy.image_length)){r.state=BCR_ACTIVE;r.image_version=legacy.version_counter;r.rollback_floor=legacy.version_counter;r.boot_attempts=0U;++r.sequence;if(bcr_commit(&r)){boot_jump_to(APP_FLASH_BASE);return false;}}
        r.state=BCR_RECOVERY; ++r.sequence; (void)bcr_commit(&r); return false;
    }
    if (r.state == BCR_RECOVERY) return false;
    if (r.state != BCR_ACTIVE && r.state != BCR_TRIAL && r.state != BCR_ROLLBACK) return false;
    if (!boot_app_vectors_valid(APP_FLASH_BASE)) {
        r.state = BCR_ROLLBACK;
        r.boot_attempts = BOOTLOADER_TRIAL_LIMIT;
        ++r.sequence;
        if (bcr_commit(&r)) (void)bootloader_select_image();
        return false;
    }
    boot_jump_to(APP_FLASH_BASE); return false;
}
