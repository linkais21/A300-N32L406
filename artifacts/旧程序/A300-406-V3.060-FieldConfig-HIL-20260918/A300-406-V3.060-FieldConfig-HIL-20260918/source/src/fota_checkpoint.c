#include "fota_checkpoint.h"
#include "ext_flash_store.h"
#include "crc32.h"
#include <string.h>
static bool payload_valid(const fota_checkpoint_t *r)
{
    return r->expected_length <= EXT_FLASH_CANDIDATE_SIZE &&
           r->offset <= r->expected_length && r->offset % FLASH_SECTOR_SIZE == 0U &&
           memchr(r->url, 0, sizeof r->url) != NULL &&
           memchr(r->etag, 0, sizeof r->etag) != NULL &&
           (r->expected_length ? r->url[0] != 0 : r->url[0] == 0);
}

static bool valid(const fota_checkpoint_t *r)
{
    return r->magic == FOTA_CHECKPOINT_MAGIC &&
           r->format_version == FOTA_CHECKPOINT_FORMAT &&
           r->record_length == sizeof *r &&
           r->commit_marker == FOTA_CHECKPOINT_MARKER && payload_valid(r) &&
           crc32_compute(r, offsetof(fota_checkpoint_t, crc32)) == r->crc32;
}

/* Read failure is distinct from an invalid/torn record: do not guess which
 * sector is expendable when the other sector could not be inspected. */
static bool newest(fota_checkpoint_t *out, uint32_t *selected)
{
    fota_checkpoint_t other;
    bool va, vb;
    *selected = 0U;
    if (!ext_flash_read(EXT_FLASH_OWNER_OTA, FOTA_CHECKPOINT_SLOT_A, out, sizeof *out) ||
        !ext_flash_read(EXT_FLASH_OWNER_OTA, FOTA_CHECKPOINT_SLOT_B, &other, sizeof other))
        return false;
    va = valid(out); vb = valid(&other);
    if (va) *selected = FOTA_CHECKPOINT_SLOT_A;
    if (vb && (!va || (uint32_t)(other.sequence - out->sequence) < 0x80000000UL)) {
        *out = other;
        *selected = FOTA_CHECKPOINT_SLOT_B;
    }
    return true;
}

bool fota_checkpoint_load(const char *url, uint32_t expected_length, fota_checkpoint_t *out)
{
    fota_checkpoint_t record;
    uint32_t selected;
    if (!url || !out || !expected_length ||
        !newest(&record, &selected) || !selected ||
        record.expected_length != expected_length || strcmp(record.url, url) != 0)
        return false;
    *out = record;
    return true;
}

static bool write_record(const fota_checkpoint_t *record)
{
    fota_checkpoint_t r = *record, check;
    uint32_t selected, addr;
    if (!newest(&check, &selected)) return false;
    r.sequence = selected ? check.sequence + 1U : 0U;
    addr = selected == FOTA_CHECKPOINT_SLOT_A ? FOTA_CHECKPOINT_SLOT_B : FOTA_CHECKPOINT_SLOT_A;
    r.magic = FOTA_CHECKPOINT_MAGIC;
    r.format_version = FOTA_CHECKPOINT_FORMAT;
    r.record_length = sizeof r;
    r.commit_marker = 0xFFFFFFFFUL;
    r.crc32 = crc32_compute(&r, offsetof(fota_checkpoint_t, crc32));
    if (!ext_flash_erase(EXT_FLASH_OWNER_OTA, addr, FLASH_SECTOR_SIZE) ||
        !ext_flash_write_verified(EXT_FLASH_OWNER_OTA, addr, &r,
                                  offsetof(fota_checkpoint_t, commit_marker))) return false;
    r.commit_marker = FOTA_CHECKPOINT_MARKER;
    if (!ext_flash_write_verified(EXT_FLASH_OWNER_OTA,
            addr + offsetof(fota_checkpoint_t, commit_marker), &r.commit_marker, sizeof r.commit_marker) ||
        !ext_flash_read(EXT_FLASH_OWNER_OTA, addr, &check, sizeof check)) return false;
    return valid(&check) && memcmp(&check, &r, sizeof r) == 0;
}

bool fota_checkpoint_commit(const fota_checkpoint_t *record)
{
    return record && record->expected_length && payload_valid(record) && write_record(record);
}

bool fota_checkpoint_clear(void)
{
    fota_checkpoint_t tombstone;
    memset(&tombstone, 0, sizeof tombstone);
    return write_record(&tombstone);
}

static bool authorization_payload_valid(const fota_authorization_t *r)
{
    return r->package_length >= 32U &&
           r->package_length <= EXT_FLASH_CANDIDATE_SIZE &&
           r->package_version != 0U && r->target_address == 0x08006000UL &&
           r->signing_key_id != 0U;
}

static bool authorization_valid(const fota_authorization_t *r)
{
    return r->magic == FOTA_AUTH_MAGIC &&
           r->format_version == FOTA_AUTH_FORMAT &&
           r->record_length == sizeof *r &&
           r->commit_marker == FOTA_AUTH_MARKER &&
           authorization_payload_valid(r) &&
           crc32_compute(r, offsetof(fota_authorization_t, crc32)) == r->crc32;
}

static bool authorization_newest(fota_authorization_t *out, uint32_t *selected)
{
    fota_authorization_t other;
    bool va, vb;
    *selected = 0U;
    if (!ext_flash_read(EXT_FLASH_OWNER_OTA, FOTA_AUTH_SLOT_A, out, sizeof *out) ||
        !ext_flash_read(EXT_FLASH_OWNER_OTA, FOTA_AUTH_SLOT_B, &other, sizeof other))
        return false;
    va = authorization_valid(out); vb = authorization_valid(&other);
    if (va) *selected = FOTA_AUTH_SLOT_A;
    if (vb && (!va || (uint32_t)(other.sequence - out->sequence) < 0x80000000UL)) {
        *out = other;
        *selected = FOTA_AUTH_SLOT_B;
    }
    return true;
}

bool fota_authorization_load(fota_authorization_t *out)
{
    uint32_t selected;
    return out && authorization_newest(out, &selected) && selected != 0U;
}

static bool authorization_write(const fota_authorization_t *record)
{
    fota_authorization_t r = *record, check;
    uint32_t selected, addr;
    if (!authorization_newest(&check, &selected)) return false;
    r.sequence = selected ? check.sequence + 1U : 0U;
    addr = selected == FOTA_AUTH_SLOT_A ? FOTA_AUTH_SLOT_B : FOTA_AUTH_SLOT_A;
    r.magic = FOTA_AUTH_MAGIC;
    r.format_version = FOTA_AUTH_FORMAT;
    r.record_length = sizeof r;
    r.commit_marker = 0xFFFFFFFFUL;
    r.crc32 = crc32_compute(&r, offsetof(fota_authorization_t, crc32));
    if (!ext_flash_erase(EXT_FLASH_OWNER_OTA, addr, FLASH_SECTOR_SIZE) ||
        !ext_flash_write_verified(EXT_FLASH_OWNER_OTA, addr, &r,
                                  offsetof(fota_authorization_t, commit_marker)))
        return false;
    r.commit_marker = FOTA_AUTH_MARKER;
    if (!ext_flash_write_verified(EXT_FLASH_OWNER_OTA,
            addr + offsetof(fota_authorization_t, commit_marker),
            &r.commit_marker, sizeof r.commit_marker) ||
        !ext_flash_read(EXT_FLASH_OWNER_OTA, addr, &check, sizeof check))
        return false;
    return authorization_valid(&check) && memcmp(&check, &r, sizeof r) == 0;
}

bool fota_authorization_commit(const fota_authorization_t *record)
{
    return record && authorization_payload_valid(record) && authorization_write(record);
}

bool fota_authorization_clear(void)
{
    fota_authorization_t tombstone;
    memset(&tombstone, 0, sizeof tombstone);
    return authorization_write(&tombstone);
}
