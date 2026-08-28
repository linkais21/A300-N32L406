#include "blind_zone.h"
#include "ext_flash_layout.h"
#include "ext_flash_store.h"
#include <stddef.h>
#include <string.h>

#define BZ_META_MAGIC          0x425A4D31UL /* BZM1 */
#define BZ_RECORD_MAGIC        0x425A5231UL /* BZR1 */
#define BZ_FORMAT_VERSION      1U
#define BZ_COMMIT_MARKER       0x434D4954UL /* CMIT */
#define BZ_META_BYTES          40U
#define BZ_RECORD_BYTES        64U
#define BZ_META_ENTRIES        (FLASH_SECTOR_SIZE / BZ_META_BYTES)
#define BZ_DATA_ADDR           (EXT_FLASH_BLIND_ADDR + FLASH_SECTOR_SIZE)
#define BZ_DATA_SIZE           (640UL * 1024UL)
#define BZ_DATA_PER_SECTOR     (FLASH_SECTOR_SIZE / BZ_RECORD_BYTES)
#define BZ_RECOVERY_READS      16U

#if (EXT_FLASH_BLIND_SIZE != (FLASH_SECTOR_SIZE + BZ_DATA_SIZE))
#error "blind-zone layout must be one metadata sector plus 640 KiB data"
#endif
#if (BZ_RECORD_BYTES * BLIND_ZONE_PHYSICAL_SLOTS != BZ_DATA_SIZE)
#error "blind-zone physical slot count does not match the data region"
#endif

#if defined(__GNUC__)
#define BZ_PACKED __attribute__((packed))
#else
#define BZ_PACKED
#pragma pack(push, 1)
#endif

typedef struct BZ_PACKED {
    uint32_t magic;
    uint16_t version;
    uint16_t entry_size;
    uint32_t generation;
    uint32_t head_slot;
    uint32_t count;
    uint32_t next_slot;
    uint32_t next_sequence;
    uint32_t reserved;
    uint32_t crc32;
    uint32_t commit_marker;
} bz_meta_t;

typedef struct BZ_PACKED {
    uint32_t magic;
    uint16_t version;
    uint16_t length;
    uint32_t sequence;
    uint8_t location[BLIND_ZONE_LOCATION_MAX];
    uint8_t reserved[4];
    uint32_t crc32;
    uint32_t commit_marker;
} bz_flash_record_t;

#if !defined(__GNUC__)
#pragma pack(pop)
#endif

typedef char bz_meta_size_check[(sizeof(bz_meta_t) == BZ_META_BYTES) ? 1 : -1];
typedef char bz_record_size_check[(sizeof(bz_flash_record_t) == BZ_RECORD_BYTES) ? 1 : -1];

typedef enum {
    BZ_RECOVERY_IDLE = 0,
    BZ_RECOVERY_META,
    BZ_RECOVERY_DATA,
    BZ_RECOVERY_FINALIZE,
    BZ_RECOVERY_RECONCILE,
    BZ_RECOVERY_READY,
} bz_recovery_state_t;

typedef struct {
    bool valid;
    uint32_t first_slot;
    uint32_t last_slot;
    uint32_t length;
    uint32_t span;
    uint32_t gap;
    uint32_t first_sequence;
    uint32_t last_sequence;
} bz_run_t;

static bz_recovery_state_t s_recovery;
static uint32_t s_head_slot;
static uint32_t s_count;
static uint32_t s_span;
static uint32_t s_next_slot;
static uint32_t s_next_sequence;
static uint32_t s_generation;
static uint32_t s_meta_scan_slot;
static uint32_t s_meta_next_slot;
static bool s_have_meta;
static bz_meta_t s_best_meta;
static uint32_t s_data_scan_slot;
static bz_run_t s_current_run;
static bz_run_t s_first_run;
static bz_run_t s_last_run;
static bz_run_t s_best_run;
static uint32_t s_reconcile_cursor;
static uint32_t s_reconcile_scanned;

static bool commit_meta_locked(uint32_t head, uint32_t count, uint32_t span,
                               uint32_t next, uint32_t next_sequence);

static void begin_reconcile(void)
{
    s_reconcile_cursor = s_next_slot;
    s_reconcile_scanned = 0U;
    s_recovery = BZ_RECOVERY_RECONCILE;
}

static uint32_t crc32_bytes(const void *data, uint32_t length)
{
    const uint8_t *bytes = (const uint8_t *)data;
    uint32_t crc = 0xffffffffUL;
    uint32_t i;
    uint8_t bit;
    for (i = 0U; i < length; ++i) {
        crc ^= bytes[i];
        for (bit = 0U; bit < 8U; ++bit)
            crc = (crc >> 1) ^ ((crc & 1U) ? 0xedb88320UL : 0U);
    }
    return crc ^ 0xffffffffUL;
}

static bool sequence_newer(uint32_t candidate, uint32_t reference)
{
    return (int32_t)(candidate - reference) > 0;
}

static uint32_t record_addr(uint32_t slot)
{
    return BZ_DATA_ADDR + slot * BZ_RECORD_BYTES;
}

static bool meta_erased(const bz_meta_t *meta)
{
    const uint8_t *bytes = (const uint8_t *)meta;
    uint32_t i;
    for (i = 0U; i < sizeof(*meta); ++i)
        if (bytes[i] != 0xffU) return false;
    return true;
}

static bool meta_valid(const bz_meta_t *meta)
{
    if (meta->magic != BZ_META_MAGIC || meta->version != BZ_FORMAT_VERSION ||
        meta->entry_size != sizeof(*meta) || meta->commit_marker != BZ_COMMIT_MARKER ||
        meta->head_slot >= BLIND_ZONE_PHYSICAL_SLOTS ||
        meta->next_slot >= BLIND_ZONE_PHYSICAL_SLOTS ||
        meta->count > BLIND_ZONE_LOGICAL_CAPACITY ||
        meta->reserved < meta->count || meta->reserved > BLIND_ZONE_PHYSICAL_SLOTS)
        return false;
    if (meta->count == 0U && meta->head_slot != meta->next_slot) return false;
    if (((meta->head_slot + meta->reserved) % BLIND_ZONE_PHYSICAL_SLOTS) != meta->next_slot)
        return false;
    return meta->crc32 == crc32_bytes(meta, (uint32_t)offsetof(bz_meta_t, crc32));
}

static bool flash_record_valid(const bz_flash_record_t *record)
{
    if (record->magic != BZ_RECORD_MAGIC || record->version != BZ_FORMAT_VERSION ||
        record->length > BLIND_ZONE_LOCATION_MAX ||
        record->commit_marker != BZ_COMMIT_MARKER)
        return false;
    return record->crc32 == crc32_bytes(record, (uint32_t)offsetof(bz_flash_record_t, crc32));
}

static bool read_record_locked(uint32_t slot, bz_flash_record_t *record)
{
    return ext_flash_read(EXT_FLASH_OWNER_BLIND_ZONE, record_addr(slot),
                          record, sizeof(*record));
}

static bool slot_erased(const bz_flash_record_t *record)
{
    const uint8_t *bytes = (const uint8_t *)record;
    uint32_t i;
    for (i = 0U; i < sizeof(*record); ++i)
        if (bytes[i] != 0xffU) return false;
    return true;
}

static bool sector_has_live_sequence_locked(uint32_t first_slot)
{
    uint32_t slot;
    uint32_t first_sequence = s_next_sequence - s_count;
    uint32_t last_sequence = s_next_sequence - 1U;
    for (slot = first_slot; slot < first_slot + BZ_DATA_PER_SECTOR; ++slot) {
        bz_flash_record_t record;
        if (!read_record_locked(slot, &record)) return true;
        if (flash_record_valid(&record) &&
            (int32_t)(record.sequence - first_sequence) >= 0 &&
            (int32_t)(last_sequence - record.sequence) >= 0)
            return true;
    }
    return false;
}

static uint32_t advance_to_sequence_locked(uint32_t slot, uint32_t span,
                                           uint32_t target_sequence,
                                           uint32_t *used_out)
{
    uint32_t used;
    for (used = 0U; used < span; ++used) {
        bz_flash_record_t record;
        if (!read_record_locked(slot, &record)) break;
        if (flash_record_valid(&record) && record.sequence == target_sequence) {
            if (used_out != NULL) *used_out = used;
            return slot;
        }
        slot = (slot + 1U) % BLIND_ZONE_PHYSICAL_SLOTS;
    }
    if (used_out != NULL) *used_out = span;
    return BLIND_ZONE_PHYSICAL_SLOTS;
}

static bool adopt_record_locked(uint32_t record_slot, uint32_t span)
{
    uint32_t head = s_head_slot;
    uint32_t count = s_count;
    if (count == BLIND_ZONE_LOGICAL_CAPACITY) {
        uint32_t skipped;
        uint32_t new_head = advance_to_sequence_locked(
            head, span, s_next_sequence - count + 1U, &skipped);
        if (new_head >= BLIND_ZONE_PHYSICAL_SLOTS) return false;
        head = new_head;
        span -= skipped;
    } else {
        ++count;
    }
    return commit_meta_locked(head, count, span,
                              (record_slot + 1U) % BLIND_ZONE_PHYSICAL_SLOTS,
                              s_next_sequence + 1U);
}

static void apply_state(uint32_t head, uint32_t count, uint32_t span, uint32_t next,
                        uint32_t next_sequence)
{
    s_head_slot = head;
    s_count = count;
    s_span = span;
    s_next_slot = next;
    s_next_sequence = next_sequence;
}

static bool commit_meta_locked(uint32_t head, uint32_t count, uint32_t span,
                               uint32_t next,
                               uint32_t next_sequence)
{
    bz_meta_t meta;
    uint32_t commit = BZ_COMMIT_MARKER;
    uint32_t address;
    if (s_meta_next_slot >= BZ_META_ENTRIES) {
        if (!ext_flash_erase(EXT_FLASH_OWNER_BLIND_ZONE, EXT_FLASH_BLIND_ADDR,
                             FLASH_SECTOR_SIZE))
            return false;
        s_meta_next_slot = 0U;
    }
    memset(&meta, 0, sizeof(meta));
    meta.magic = BZ_META_MAGIC;
    meta.version = BZ_FORMAT_VERSION;
    meta.entry_size = sizeof(meta);
    meta.generation = s_generation + 1U;
    meta.head_slot = head;
    meta.count = count;
    meta.next_slot = next;
    meta.next_sequence = next_sequence;
    meta.reserved = span;
    meta.crc32 = crc32_bytes(&meta, (uint32_t)offsetof(bz_meta_t, crc32));
    meta.commit_marker = 0xffffffffUL;
    address = EXT_FLASH_BLIND_ADDR + s_meta_next_slot * BZ_META_BYTES;
    if (!ext_flash_write_verified(EXT_FLASH_OWNER_BLIND_ZONE, address, &meta,
                                  (uint32_t)offsetof(bz_meta_t, commit_marker)) ||
        !ext_flash_write_verified(EXT_FLASH_OWNER_BLIND_ZONE,
                                  address + offsetof(bz_meta_t, commit_marker),
                                  &commit, sizeof(commit))) {
        /* The failed entry may be partly programmed. Never attempt a NOR
         * rewrite; reboot metadata scanning makes the same slot decision. */
        ++s_meta_next_slot;
        return false;
    }
    s_generation = meta.generation;
    ++s_meta_next_slot;
    apply_state(head, count, span, next, next_sequence);
    return true;
}

static void consider_run(const bz_run_t *run)
{
    if (!run->valid) return;
    if (!s_first_run.valid) s_first_run = *run;
    s_last_run = *run;
    if (!s_best_run.valid || sequence_newer(run->last_sequence, s_best_run.last_sequence) ||
        (run->last_sequence == s_best_run.last_sequence && run->length > s_best_run.length))
        s_best_run = *run;
}

static void finish_current_run(void)
{
    consider_run(&s_current_run);
    memset(&s_current_run, 0, sizeof(s_current_run));
}

static void scan_record(uint32_t slot, const bz_flash_record_t *record)
{
    if (!flash_record_valid(record)) {
        if (s_current_run.valid) ++s_current_run.gap;
        return;
    }
    if (s_current_run.valid &&
        record->sequence == s_current_run.last_sequence + 1U) {
        s_current_run.last_slot = slot;
        s_current_run.last_sequence = record->sequence;
        ++s_current_run.length;
        s_current_run.span += s_current_run.gap + 1U;
        s_current_run.gap = 0U;
        return;
    }
    finish_current_run();
    s_current_run.valid = true;
    s_current_run.first_slot = slot;
    s_current_run.last_slot = slot;
    s_current_run.length = 1U;
    s_current_run.span = 1U;
    s_current_run.first_sequence = record->sequence;
    s_current_run.last_sequence = record->sequence;
}

static void complete_data_scan(void)
{
    bz_run_t merged;
    finish_current_run();
    if (s_first_run.valid && s_last_run.valid &&
        s_first_run.first_slot == 0U &&
        s_last_run.last_slot == BLIND_ZONE_PHYSICAL_SLOTS - 1U &&
        s_first_run.first_slot != s_last_run.first_slot &&
        s_first_run.first_sequence == s_last_run.last_sequence + 1U) {
        merged = s_last_run;
        merged.last_slot = s_first_run.last_slot;
        merged.last_sequence = s_first_run.last_sequence;
        merged.length += s_first_run.length;
        merged.span = (s_first_run.last_slot + BLIND_ZONE_PHYSICAL_SLOTS + 1U -
                       s_last_run.first_slot) % BLIND_ZONE_PHYSICAL_SLOTS;
        if (merged.span == 0U) merged.span = BLIND_ZONE_PHYSICAL_SLOTS;
        consider_run(&merged);
    }
    if (!s_best_run.valid) {
        apply_state(0U, 0U, 0U, 0U, 1U);
    } else {
        uint32_t count = s_best_run.length;
        uint32_t head = s_best_run.first_slot;
        uint32_t span = s_best_run.span;
        if (count > BLIND_ZONE_LOGICAL_CAPACITY) count = BLIND_ZONE_LOGICAL_CAPACITY;
        if (s_best_run.length > count) {
            uint32_t skipped;
            uint32_t trimmed = advance_to_sequence_locked(
                head, span, s_best_run.last_sequence - count + 1U, &skipped);
            if (trimmed < BLIND_ZONE_PHYSICAL_SLOTS) {
                head = trimmed;
                span -= skipped;
            }
        }
        apply_state(head, count, span,
                    (s_best_run.last_slot + 1U) % BLIND_ZONE_PHYSICAL_SLOTS,
                    s_best_run.last_sequence + 1U);
    }
    s_recovery = BZ_RECOVERY_FINALIZE;
}

bool blind_zone_init(void)
{
    s_recovery = BZ_RECOVERY_META;
    s_meta_scan_slot = 0U;
    s_meta_next_slot = 0U;
    s_have_meta = false;
    memset(&s_best_meta, 0, sizeof(s_best_meta));
    s_data_scan_slot = 0U;
    memset(&s_current_run, 0, sizeof(s_current_run));
    memset(&s_first_run, 0, sizeof(s_first_run));
    memset(&s_last_run, 0, sizeof(s_last_run));
    memset(&s_best_run, 0, sizeof(s_best_run));
    s_reconcile_cursor = 0U;
    s_reconcile_scanned = 0U;
    apply_state(0U, 0U, 0U, 0U, 1U);
    s_generation = 0U;
    return true;
}

bool blind_zone_ready(void)
{
    return s_recovery == BZ_RECOVERY_READY;
}

void blind_zone_recovery_process(void)
{
    uint32_t reads = 0U;
    if (s_recovery == BZ_RECOVERY_IDLE || s_recovery == BZ_RECOVERY_READY) return;
    if (!ext_flash_try_lock(EXT_FLASH_OWNER_BLIND_ZONE)) return;

    if (s_recovery == BZ_RECOVERY_META) {
        while (reads++ < BZ_RECOVERY_READS && s_meta_scan_slot < BZ_META_ENTRIES) {
            bz_meta_t meta;
            if (!ext_flash_read(EXT_FLASH_OWNER_BLIND_ZONE,
                                EXT_FLASH_BLIND_ADDR + s_meta_scan_slot * BZ_META_BYTES,
                                &meta, sizeof(meta)))
                break;
            if (!meta_erased(&meta)) s_meta_next_slot = s_meta_scan_slot + 1U;
            if (meta_valid(&meta) &&
                (!s_have_meta || sequence_newer(meta.generation, s_best_meta.generation))) {
                s_best_meta = meta;
                s_have_meta = true;
            }
            ++s_meta_scan_slot;
        }
        if (s_meta_scan_slot == BZ_META_ENTRIES) {
            if (s_have_meta) {
                apply_state(s_best_meta.head_slot, s_best_meta.count,
                            s_best_meta.reserved,
                            s_best_meta.next_slot, s_best_meta.next_sequence);
                s_generation = s_best_meta.generation;
                begin_reconcile();
            } else {
                s_recovery = BZ_RECOVERY_DATA;
            }
        }
    } else if (s_recovery == BZ_RECOVERY_DATA) {
        while (reads++ < BZ_RECOVERY_READS &&
               s_data_scan_slot < BLIND_ZONE_PHYSICAL_SLOTS) {
            bz_flash_record_t record;
            if (!read_record_locked(s_data_scan_slot, &record)) break;
            scan_record(s_data_scan_slot, &record);
            ++s_data_scan_slot;
        }
        if (s_data_scan_slot == BLIND_ZONE_PHYSICAL_SLOTS) complete_data_scan();
    } else if (s_recovery == BZ_RECOVERY_RECONCILE) {
        while (reads < BZ_RECOVERY_READS &&
               s_reconcile_scanned < BLIND_ZONE_PHYSICAL_SLOTS) {
            bz_flash_record_t record;
            uint32_t adopted_span;
            if (!read_record_locked(s_reconcile_cursor, &record)) break;
            adopted_span = s_span + s_reconcile_scanned + 1U;
            if (flash_record_valid(&record) &&
                record.sequence == s_next_sequence &&
                adopted_span <= BLIND_ZONE_PHYSICAL_SLOTS) {
                if (adopt_record_locked(s_reconcile_cursor, adopted_span))
                    s_recovery = BZ_RECOVERY_READY;
                break;
            }
            s_reconcile_cursor =
                (s_reconcile_cursor + 1U) % BLIND_ZONE_PHYSICAL_SLOTS;
            ++s_reconcile_scanned;
            ++reads;
        }
        if (s_reconcile_scanned == BLIND_ZONE_PHYSICAL_SLOTS)
            s_recovery = BZ_RECOVERY_READY;
    } else if (s_recovery == BZ_RECOVERY_FINALIZE) {
        if (commit_meta_locked(s_head_slot, s_count, s_span,
                               s_next_slot, s_next_sequence))
            s_recovery = BZ_RECOVERY_READY;
    }
    ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
}

blind_zone_result_t blind_zone_append(const blind_zone_record_t *record)
{
    bz_flash_record_t flash_record;
    bz_flash_record_t existing;
    uint32_t commit = BZ_COMMIT_MARKER;
    uint32_t head;
    uint32_t count;
    uint32_t span;
    uint32_t write_slot;
    if (record == NULL || record->length > BLIND_ZONE_LOCATION_MAX)
        return BLIND_ZONE_INVALID;
    if (!blind_zone_ready()) return BLIND_ZONE_BUSY;
    if (!ext_flash_try_lock(EXT_FLASH_OWNER_BLIND_ZONE)) return BLIND_ZONE_BUSY;

    /* A completed data write with torn metadata is adopted before accepting new input. */
    if (read_record_locked(s_next_slot, &existing) && flash_record_valid(&existing) &&
        existing.sequence == s_next_sequence) {
        if (!adopt_record_locked(s_next_slot, s_span + 1U)) {
            begin_reconcile();
            ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
            return BLIND_ZONE_IO_ERROR;
        }
        /* Continue with the caller's record after adopting the prior committed write. */
    }

    write_slot = s_next_slot;
    span = s_span;
    for (;;) {
        if ((write_slot % BZ_DATA_PER_SECTOR) == 0U) {
            if (sector_has_live_sequence_locked(write_slot) ||
                !ext_flash_erase(EXT_FLASH_OWNER_BLIND_ZONE,
                                 record_addr(write_slot), FLASH_SECTOR_SIZE)) {
                ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
                return BLIND_ZONE_IO_ERROR;
            }
        }
        if (!read_record_locked(write_slot, &existing)) {
            ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
            return BLIND_ZONE_IO_ERROR;
        }
        if (slot_erased(&existing)) break;
        if (span >= BLIND_ZONE_PHYSICAL_SLOTS - 1U) {
            ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
            return BLIND_ZONE_IO_ERROR;
        }
        ++span;
        write_slot = (write_slot + 1U) % BLIND_ZONE_PHYSICAL_SLOTS;
    }

    memset(&flash_record, 0, sizeof(flash_record));
    flash_record.magic = BZ_RECORD_MAGIC;
    flash_record.version = BZ_FORMAT_VERSION;
    flash_record.length = record->length;
    flash_record.sequence = s_next_sequence;
    memcpy(flash_record.location, record->location, record->length);
    flash_record.crc32 = crc32_bytes(&flash_record,
                                     (uint32_t)offsetof(bz_flash_record_t, crc32));
    flash_record.commit_marker = 0xffffffffUL;
    if (!ext_flash_write_verified(EXT_FLASH_OWNER_BLIND_ZONE, record_addr(write_slot),
                                  &flash_record,
                                  (uint32_t)offsetof(bz_flash_record_t, commit_marker)) ||
        !ext_flash_write_verified(EXT_FLASH_OWNER_BLIND_ZONE,
                                  record_addr(write_slot) +
                                      offsetof(bz_flash_record_t, commit_marker),
                                  &commit, sizeof(commit))) {
        ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
        return BLIND_ZONE_IO_ERROR;
    }

    head = s_head_slot;
    count = s_count;
    ++span;
    if (count == BLIND_ZONE_LOGICAL_CAPACITY) {
        uint32_t skipped;
        uint32_t new_head = advance_to_sequence_locked(
            head, span, s_next_sequence - count + 1U, &skipped);
        if (new_head >= BLIND_ZONE_PHYSICAL_SLOTS) {
            ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
            return BLIND_ZONE_IO_ERROR;
        }
        head = new_head;
        span -= skipped;
    } else {
        ++count;
    }
    if (!commit_meta_locked(head, count, span,
                            (write_slot + 1U) % BLIND_ZONE_PHYSICAL_SLOTS,
                            s_next_sequence + 1U)) {
        begin_reconcile();
        ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
        return BLIND_ZONE_IO_ERROR;
    }
    ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
    return BLIND_ZONE_OK;
}

uint8_t blind_zone_peek(blind_zone_record_t *records, uint8_t capacity,
                        uint32_t *first_sequence)
{
    uint8_t copied = 0U;
    uint32_t slot;
    uint32_t scanned = 0U;
    uint32_t expected;
    if (!blind_zone_ready() || records == NULL || first_sequence == NULL || capacity == 0U)
        return 0U;
    if (!ext_flash_try_lock(EXT_FLASH_OWNER_BLIND_ZONE)) return 0U;
    slot = s_head_slot;
    expected = s_next_sequence - s_count;
    while (copied < capacity && copied < s_count && scanned < s_span) {
        bz_flash_record_t record;
        if (!read_record_locked(slot, &record)) break;
        ++scanned;
        slot = (slot + 1U) % BLIND_ZONE_PHYSICAL_SLOTS;
        if (!flash_record_valid(&record) || record.sequence != expected + copied)
            continue;
        records[copied].length = (uint8_t)record.length;
        memcpy(records[copied].location, record.location, record.length);
        if (record.length < BLIND_ZONE_LOCATION_MAX)
            memset(records[copied].location + record.length, 0,
                   BLIND_ZONE_LOCATION_MAX - record.length);
        if (copied == 0U) *first_sequence = record.sequence;
        ++copied;
    }
    ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
    return copied;
}

blind_zone_result_t blind_zone_consume(uint32_t first_sequence, uint8_t count)
{
    uint32_t expected;
    uint32_t head;
    uint32_t remaining;
    uint32_t skipped;
    uint32_t span;
    if (!blind_zone_ready()) return BLIND_ZONE_BUSY;
    if (count == 0U || count > s_count) return BLIND_ZONE_INVALID;
    expected = s_next_sequence - s_count;
    if (first_sequence != expected) return BLIND_ZONE_INVALID;
    if (!ext_flash_try_lock(EXT_FLASH_OWNER_BLIND_ZONE)) return BLIND_ZONE_BUSY;
    remaining = s_count - count;
    if (remaining == 0U) {
        head = s_next_slot;
        span = 0U;
    } else {
        head = advance_to_sequence_locked(s_head_slot, s_span,
                                          first_sequence + count, &skipped);
        if (head >= BLIND_ZONE_PHYSICAL_SLOTS) {
            ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
            return BLIND_ZONE_IO_ERROR;
        }
        span = s_span - skipped;
    }
    if (!commit_meta_locked(head, remaining, span, s_next_slot, s_next_sequence)) {
        ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
        return BLIND_ZONE_IO_ERROR;
    }
    ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
    return BLIND_ZONE_OK;
}
