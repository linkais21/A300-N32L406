#include "image_install.h"
#include "image_verify.h"
#include "bcr.h"
#include "bootloader_config.h"
#include <string.h>
#include <stddef.h>

#define CANDIDATE_BASE 0x010000UL
#define LKG_BASE       0x0C0000UL
#define FACTORY_BASE   0x080000UL
#define LKG_PAYLOAD_BASE (LKG_BASE + sizeof(image_manifest_t))
#define FACTORY_PAYLOAD_BASE (FACTORY_BASE + sizeof(image_manifest_t))

static bool copy_image(uint32_t source, uint32_t target, uint32_t length)
{
    uint8_t page[BOOTLOADER_PAGE_SIZE], verify[BOOTLOADER_PAGE_SIZE];
    if (!boot_int_flash_erase(target, length)) return false;
    for (uint32_t offset=0; offset<length; offset+=sizeof page) {
        uint32_t n = (length-offset > sizeof page) ? sizeof page : length-offset;
        if (!boot_ext_read(source+offset,page,n) || !boot_int_flash_program(target+offset,page,n) || !boot_int_flash_read(target+offset,verify,n) || memcmp(page,verify,n)!=0) return false;
        boot_watchdog_feed();
    }
    return true;
}

static bool preserve_signed_package_to_lkg(const image_manifest_t *manifest)
{
    uint8_t page[BOOTLOADER_PAGE_SIZE], verify[BOOTLOADER_PAGE_SIZE];
    image_manifest_t copied;
    if (!manifest || manifest->image_length == 0U || manifest->image_length > APP_FLASH_MAX_SIZE) return false;
    uint32_t total = (uint32_t)sizeof(image_manifest_t) + manifest->image_length;
    uint32_t erase_len = (total + 4095U) & ~4095U;
    if (erase_len > 0x40000UL || !boot_ext_erase(LKG_BASE, erase_len)) return false;
    for (uint32_t offset=0; offset<sizeof(image_manifest_t) + manifest->image_length; offset+=sizeof page) {
        uint32_t n=(total-offset>sizeof page)?sizeof page:total-offset;
        if (!boot_ext_read(CANDIDATE_BASE+offset,page,n) ||
            !boot_ext_write(LKG_BASE+offset,page,n) ||
            !boot_ext_read(LKG_BASE+offset,verify,n) || memcmp(page,verify,n)!=0) return false;
        boot_watchdog_feed();
    }
    return boot_ext_read(LKG_BASE,&copied,sizeof copied) &&
           verify_external_manifest(&copied,LKG_BASE);
}

bool install_candidate(const image_manifest_t *manifest)
{
    bcr_record_t r;
    if (verify_candidate(manifest) != IMAGE_VERIFY_OK) return false;
    r=(bcr_record_t){.sequence=1U,.state=BCR_PENDING,.image_version=manifest->version_counter,.transaction_offset=0U,.transaction_length=manifest->image_length,.target_address=manifest->target_address};
    bcr_record_t previous;
    if (bcr_load(&previous)) { r.sequence=previous.sequence+1U; r.rollback_floor=previous.rollback_floor; }
    if (!bcr_commit(&r)) return false;
    if (!copy_image(CANDIDATE_BASE+(uint32_t)sizeof(*manifest),manifest->target_address,manifest->image_length)) return false;
    r.state=BCR_TRIAL; r.boot_attempts=0U; r.transaction_offset=manifest->image_length; ++r.sequence;
    return bcr_commit(&r);
}

bool install_resume(uint32_t offset)
{
    bcr_record_t r; uint8_t page[BOOTLOADER_PAGE_SIZE], verify[BOOTLOADER_PAGE_SIZE];
    image_manifest_t m;
    if (!bcr_load(&r) || r.state != BCR_PENDING || offset > r.transaction_length || !boot_ext_read(CANDIDATE_BASE,&m,sizeof m) || verify_candidate(&m) != IMAGE_VERIFY_OK || r.target_address != m.target_address || r.transaction_length != m.image_length || r.image_version != m.version_counter || r.target_address < APP_FLASH_BASE || r.target_address > APP_FLASH_END || r.transaction_length > (APP_FLASH_END - r.target_address)) return false;
    if (offset == 0U && !boot_int_flash_erase(r.target_address, r.transaction_length)) return false;
    for (uint32_t pos=offset; pos<r.transaction_length; pos+=sizeof page) {
        uint32_t n=(r.transaction_length-pos>sizeof page)?sizeof page:r.transaction_length-pos;
        if(!boot_ext_read(CANDIDATE_BASE+sizeof(image_manifest_t)+pos,page,n)||!boot_int_flash_program(r.target_address+pos,page,n)||!boot_int_flash_read(r.target_address+pos,verify,n)||memcmp(page,verify,n)!=0)return false;
        r.transaction_offset=pos+n; ++r.sequence; if(!bcr_commit(&r)) return false; boot_watchdog_feed();
    }
    r.state=BCR_TRIAL; r.boot_attempts=0U; ++r.sequence; return bcr_commit(&r);
}

bool bootloader_select_image(void)
{
    bcr_record_t r;
    if (!bcr_load(&r)) { boot_jump_to(APP_FLASH_BASE); return false; }
    if (r.state == BCR_PENDING) return install_resume(r.transaction_offset);
    if (r.state == BCR_ACTIVE) {
        image_manifest_t m;
        if (boot_ext_read(CANDIDATE_BASE,&m,sizeof m) &&
            r.image_version == m.version_counter &&
            r.transaction_length == m.image_length &&
            r.target_address == m.target_address &&
            verify_candidate(&m) == IMAGE_VERIFY_OK) {
            /* LKG preservation is best-effort. A valid internal App must still
             * boot when the optional external Flash is absent or unavailable. */
            (void)preserve_signed_package_to_lkg(&m);
        }
        boot_jump_to(APP_FLASH_BASE);
        return false;
    }
    if ((r.state == BCR_TRIAL || r.state == BCR_ROLLBACK) && r.boot_attempts >= BOOTLOADER_TRIAL_LIMIT) {
        image_manifest_t m;
        if (boot_ext_read(LKG_BASE,&m,sizeof m) && verify_external_manifest(&m,LKG_BASE) && copy_image(LKG_PAYLOAD_BASE,APP_FLASH_BASE,m.image_length)) { r.state=BCR_ACTIVE; r.image_version=m.version_counter; r.rollback_floor=m.version_counter; r.boot_attempts=0U; ++r.sequence; if (bcr_commit(&r)) { boot_jump_to(APP_FLASH_BASE); return false; } }
        if (boot_ext_read(FACTORY_BASE,&m,sizeof m) && verify_external_manifest(&m,FACTORY_BASE) && copy_image(FACTORY_PAYLOAD_BASE,APP_FLASH_BASE,m.image_length)) { r.state=BCR_ACTIVE; r.image_version=m.version_counter; r.rollback_floor=m.version_counter; r.boot_attempts=0U; ++r.sequence; if (bcr_commit(&r)) { boot_jump_to(APP_FLASH_BASE); return false; } }
        r.state=BCR_RECOVERY; ++r.sequence; (void)bcr_commit(&r); return false;
    }
    boot_jump_to(APP_FLASH_BASE); return false;
}
