#include "sha256.h"
#include "agnss_storage.h"
#include "crc32.h"
#include "ext_flash_store.h"
#include "service_workspace.h"
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
static agnss_meta_t s_read_meta;
static uint8_t s_read_slot;
static bool s_read_valid;

uint8_t *agnss_storage_scratch(uint16_t *capacity)
{
    size_t available = 0U;
    uint8_t *buffer = service_workspace_buffer(&available);
    if (capacity) *capacity = (uint16_t)available;
    return buffer;
}

static uint32_t slot_base(uint8_t slot)
{
    return slot ? EXT_FLASH_AGNSS_SLOT_B_ADDR : EXT_FLASH_AGNSS_SLOT_A_ADDR;
}

static uint32_t meta_addr(uint8_t slot)
{
    return slot ? META_B : META_A;
}

static bool valid_meta(const agnss_meta_t *m)
{
    if (m->magic != AGNSS_MAGIC || m->commit_marker != AGNSS_COMMIT_MARKER ||
        m->length > AGNSS_MAX_DATA || m->type == GNSS_TYPE_UNKNOWN)
        return false;
    return crc32_compute((const uint8_t *)m,
                         (uint32_t)offsetof(agnss_meta_t, metadata_crc)) == m->metadata_crc;
}

static bool verify_payload(uint8_t slot, const agnss_meta_t *m)
{
    size_t capacity;
    uint8_t *buffer;
    sha256_ctx_t sh;
    uint32_t crc = 0xFFFFFFFFUL, left = m->length, off = 0;
    uint8_t h[32];
    bool ok = false;
    if (!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_AGNSS)) return false;
    buffer = service_workspace_buffer(&capacity);
    if (buffer == NULL || capacity == 0U) goto done;
    if (!ext_flash_try_lock(EXT_FLASH_OWNER_AGNSS)) goto done;
    sha256_init(&sh);
    while (left) {
        uint16_t n = (uint16_t)(left > capacity ? capacity : left);
        if (!ext_flash_read(EXT_FLASH_OWNER_AGNSS, slot_base(slot) + off, buffer, n)) {
            ext_flash_unlock(EXT_FLASH_OWNER_AGNSS);
            goto done;
        }
        crc = crc32_update(crc, buffer, n);
        sha256_update(&sh, buffer, n);
        off += n;
        left -= n;
    }
    sha256_final(&sh, h);
    ext_flash_unlock(EXT_FLASH_OWNER_AGNSS);
    ok = (crc ^ 0xFFFFFFFFUL) == m->crc32 && memcmp(h, m->sha256, 32) == 0;
done:
    service_workspace_release(SERVICE_WORKSPACE_OWNER_AGNSS);
    return ok;
}

bool agnss_storage_init(void)
{
    agnss_storage_abort();
    return true;
}

bool agnss_storage_begin(uint8_t slot)
{
    agnss_storage_read_close();
    if (slot > 1 || !ext_flash_try_lock(EXT_FLASH_OWNER_AGNSS)) return false;
    s_slot = slot;
    s_pos = 0;
    s_active = false;
    if (!ext_flash_erase(EXT_FLASH_OWNER_AGNSS, slot_base(slot), EXT_FLASH_AGNSS_SLOT_SIZE)) {
        ext_flash_unlock(EXT_FLASH_OWNER_AGNSS);
        return false;
    }
    /* Successful begin retains the Flash owner until commit or abort. */
    s_active = true;
    return true;
}

bool agnss_storage_write(const void *d, uint16_t n)
{
    agnss_storage_read_close();
    if (!s_active || !d || n > SERVICE_WORKSPACE_CAPACITY || s_pos + n > AGNSS_MAX_DATA) {
        agnss_storage_abort();
        return false;
    }
    if (!ext_flash_write_verified(EXT_FLASH_OWNER_AGNSS, slot_base(s_slot) + s_pos, d, n)) {
        agnss_storage_abort();
        return false;
    }
    s_pos += n;
    return true;
}

bool agnss_storage_commit(const agnss_meta_t *in)
{
    agnss_meta_t m;
    sha256_ctx_t sh;
    uint32_t left, off = 0, crc = 0xFFFFFFFFUL;
    size_t capacity;
    uint8_t *buffer;
    agnss_storage_read_close();
    if (!s_active || !in || in->length != s_pos) {
        agnss_storage_abort();
        return false;
    }
    if (!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_AGNSS)) {
        agnss_storage_abort();
        return false;
    }
    buffer = service_workspace_buffer(&capacity);
    if (buffer == NULL || capacity == 0U) goto fail;

    /* Re-read the written payload before publishing metadata. */
    m = *in;
    m.magic = AGNSS_MAGIC;
    m.commit_marker = 0xFFFFFFFFUL;
    memset(m.reserved, 0, sizeof m.reserved);
    sha256_init(&sh);
    left = m.length;
    while (left) {
        uint16_t n = (uint16_t)(left > capacity ? capacity : left);
        if (!ext_flash_read(EXT_FLASH_OWNER_AGNSS, slot_base(s_slot) + off, buffer, n))
            goto fail;
        crc = crc32_update(crc, buffer, n);
        sha256_update(&sh, buffer, n);
        off += n;
        left -= n;
    }
    m.crc32 = crc ^ 0xFFFFFFFFUL;
    sha256_final(&sh, m.sha256);
    m.timestamp = m.timestamp ? m.timestamp : TICK_MS();
    m.metadata_crc = crc32_compute((const uint8_t *)&m,
                                  (uint32_t)offsetof(agnss_meta_t, metadata_crc));

    /* The marker is the last write: an interrupted metadata body stays invalid. */
    if (!ext_flash_erase(EXT_FLASH_OWNER_AGNSS, meta_addr(s_slot), FLASH_SECTOR_SIZE))
        goto fail;
    if (!ext_flash_write_verified(EXT_FLASH_OWNER_AGNSS, meta_addr(s_slot), &m,
                                 (uint32_t)offsetof(agnss_meta_t, commit_marker)))
        goto fail;
    if (!ext_flash_write_verified(EXT_FLASH_OWNER_AGNSS,
                                 meta_addr(s_slot) + offsetof(agnss_meta_t, commit_marker),
                                 &((uint32_t){AGNSS_COMMIT_MARKER}), 4))
        goto fail;
    ext_flash_unlock(EXT_FLASH_OWNER_AGNSS);
    service_workspace_release(SERVICE_WORKSPACE_OWNER_AGNSS);
    s_active = false;
    s_latest_slot = s_slot;
    return true;
fail:
    service_workspace_release(SERVICE_WORKSPACE_OWNER_AGNSS);
    agnss_storage_abort();
    return false;
}

bool agnss_storage_get_latest(agnss_meta_t *out)
{
    if (!out) return false;
    agnss_meta_t a, b;
    bool la = ext_flash_try_lock(EXT_FLASH_OWNER_AGNSS);
    bool va = la && ext_flash_read(EXT_FLASH_OWNER_AGNSS, META_A, &a, sizeof a) && valid_meta(&a);
    if (la) ext_flash_unlock(EXT_FLASH_OWNER_AGNSS);
    bool lb = ext_flash_try_lock(EXT_FLASH_OWNER_AGNSS);
    bool vb = lb && ext_flash_read(EXT_FLASH_OWNER_AGNSS, META_B, &b, sizeof b) && valid_meta(&b);
    if (lb) ext_flash_unlock(EXT_FLASH_OWNER_AGNSS);
    if (va && !verify_payload(0, &a)) va = false;
    if (vb && !verify_payload(1, &b)) vb = false;
    if (!va && !vb) return false;
    if (!vb || (va && a.sequence >= b.sequence)) {
        *out = a;
        s_latest_slot = 0;
    } else {
        *out = b;
        s_latest_slot = 1;
    }
    return true;
}

bool agnss_storage_read(uint32_t off, void *buf, uint16_t n)
{
    agnss_meta_t m;
    bool ok;
    if (!buf || off > AGNSS_MAX_DATA || n > AGNSS_MAX_DATA - off ||
        !agnss_storage_get_latest(&m) || off > m.length || n > m.length - off ||
        n > SERVICE_WORKSPACE_CAPACITY)
        return false;
    if (!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_AGNSS)) return false;
    if (!ext_flash_try_lock(EXT_FLASH_OWNER_AGNSS)) {
        service_workspace_release(SERVICE_WORKSPACE_OWNER_AGNSS);
        return false;
    }
    ok = ext_flash_read(EXT_FLASH_OWNER_AGNSS, slot_base(s_latest_slot) + off, buf, n);
    ext_flash_unlock(EXT_FLASH_OWNER_AGNSS);
    service_workspace_release(SERVICE_WORKSPACE_OWNER_AGNSS);
    return ok;
}

void agnss_storage_abort(void)
{
    agnss_storage_read_close();
    if (s_active) {
        s_active = false;
        ext_flash_unlock(EXT_FLASH_OWNER_AGNSS);
    }
}

void agnss_storage_read_close(void)
{
    s_read_valid = false;
}

bool agnss_storage_read_open(agnss_meta_t *meta)
{
    if (!meta || s_active) return false;
    if (!s_read_valid) {
        if (!agnss_storage_get_latest(&s_read_meta)) return false;
        s_read_slot = s_latest_slot;
        s_read_valid = true;
    }
    *meta = s_read_meta;
    return true;
}

bool agnss_storage_read_chunk(uint32_t off, void *buf, uint16_t n)
{
    agnss_meta_t current;
    bool ok = false;
    if (!s_read_valid || s_active || !buf || n > SERVICE_WORKSPACE_CAPACITY ||
        off > s_read_meta.length || n > s_read_meta.length - off) goto done;
    if (!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_AGNSS)) goto done;
    if (ext_flash_try_lock(EXT_FLASH_OWNER_AGNSS)) {
        /* Metadata identity binds length, sequence, CRC/SHA and commit marker
         * to the verified slot. Never silently select another slot mid-read. */
        ok = ext_flash_read(EXT_FLASH_OWNER_AGNSS, meta_addr(s_read_slot),
                            &current, sizeof current) &&
             memcmp(&current, &s_read_meta, sizeof current) == 0 &&
             ext_flash_read(EXT_FLASH_OWNER_AGNSS, slot_base(s_read_slot) + off, buf, n);
        ext_flash_unlock(EXT_FLASH_OWNER_AGNSS);
    }
    service_workspace_release(SERVICE_WORKSPACE_OWNER_AGNSS);
done:
    if (!ok) agnss_storage_read_close();
    return ok;
}
