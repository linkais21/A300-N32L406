#include "blind_zone.h"
#include "crc32.h"
#include "ext_flash_layout.h"
#include "ext_flash_store.h"
#include <stddef.h>
#include <string.h>

#define BZ_META_MAGIC          0x425A4D31UL /* BZM1 */
#define BZ_RECORD_MAGIC        0x425A5231UL /* BZR1 */
#define BZ_SCRATCH_MAGIC       0x425A5331UL /* BZS1 */
#define BZ_FORMAT_VERSION      3U
#define BZ_COMMIT_MARKER       0x434D4954UL /* CMIT */
#define BZ_META_BYTES          40U
#define BZ_RECORD_BYTES        64U
#define BZ_META_ENTRIES        (FLASH_SECTOR_SIZE / BZ_META_BYTES)
#define BZ_DATA_ADDR           (EXT_FLASH_BLIND_ADDR + FLASH_SECTOR_SIZE)
#define BZ_DATA_SIZE           (636UL * 1024UL)
#define BZ_SCRATCH_ADDR        (BZ_DATA_ADDR + BZ_DATA_SIZE)
#define BZ_DATA_PER_SECTOR     (FLASH_SECTOR_SIZE / BZ_RECORD_BYTES)
#define BZ_DATA_SECTORS        (BZ_DATA_SIZE / FLASH_SECTOR_SIZE)
#define BZ_RECOVERY_READS      16U
#define BZ_RECORD_PREPARED     0xffffffffUL
#define BZ_RECORD_CONSUMED     0x00000000UL
#define BZ_PEEK_SNAPSHOT_MAX   BLIND_ZONE_PEEK_MAX

#if (EXT_FLASH_BLIND_SIZE != (FLASH_SECTOR_SIZE + BZ_DATA_SIZE + FLASH_SECTOR_SIZE))
#error "blind-zone layout must be metadata, 636 KiB data and one scratch sector"
#endif
#if (BZ_SCRATCH_ADDR != 0x1B0000UL)
#error "blind-zone scratch address changed"
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
    uint32_t event_id;
    uint32_t sequence;
    uint8_t location[BLIND_ZONE_LOCATION_MAX];
    uint32_t crc32;
    uint32_t commit_marker;
} bz_flash_record_t;

typedef struct BZ_PACKED {
    uint32_t magic;
    uint16_t version;
    uint16_t header_size;
    uint32_t victim_sector;
    uint32_t generation;
    uint64_t slot_bitmap;
    uint32_t record_count;
    uint32_t payload_crc32;
    uint32_t reserved[6];
    uint32_t header_crc32;
    uint32_t commit_marker;
} bz_scratch_header_t;

#if !defined(__GNUC__)
#pragma pack(pop)
#endif

typedef char bz_meta_size_check[(sizeof(bz_meta_t) == BZ_META_BYTES) ? 1 : -1];
typedef char bz_record_size_check[(sizeof(bz_flash_record_t) == BZ_RECORD_BYTES) ? 1 : -1];
typedef char bz_scratch_header_size_check[(sizeof(bz_scratch_header_t) == BZ_RECORD_BYTES) ? 1 : -1];

typedef enum {
    BZ_RECOVERY_IDLE = 0,
    BZ_RECOVERY_SCRATCH_CHECK,
    BZ_RECOVERY_SCRATCH_VALIDATE,
    BZ_RECOVERY_SCRATCH_VICTIM_VALIDATE,
    BZ_RECOVERY_SCRATCH_DISCARD,
    BZ_RECOVERY_META,
    BZ_RECOVERY_DATA,
    BZ_RECOVERY_FINALIZE,
    BZ_RECOVERY_RECONCILE,
    BZ_RECOVERY_CLEANUP,
    BZ_RECOVERY_CONSUME,
    BZ_RECOVERY_CONSUME_META,
    BZ_RECOVERY_ROLLOVER_SCAN,
    BZ_RECOVERY_ROLLOVER_ERASE,
    BZ_RECOVERY_REPAIR_BEGIN_ERASE,
    BZ_RECOVERY_REPAIR_BACKUP,
    BZ_RECOVERY_REPAIR_HEADER,
    BZ_RECOVERY_REPAIR_VALIDATE,
    BZ_RECOVERY_REPAIR_VICTIM_ERASE,
    BZ_RECOVERY_REPAIR_RESTORE,
    BZ_RECOVERY_REPAIR_VERIFY,
    BZ_RECOVERY_REPAIR_FINAL_ERASE,
    BZ_RECOVERY_READY,
} bz_recovery_state_t;

typedef enum { BZ_META_ERROR = 0, BZ_META_OK, BZ_META_PENDING } bz_meta_result_t;
typedef enum {
    BZ_SLOT_ERASED = 0,
    BZ_SLOT_PREPARED,
    BZ_SLOT_ACTIVE,
    BZ_SLOT_CONSUMED,
    BZ_SLOT_DAMAGED,
    BZ_SLOT_OLD_FORMAT,
} bz_slot_status_t;
typedef enum {
    BZ_APPEND_NONE = 0,
    BZ_APPEND_UNCERTAIN,
    BZ_APPEND_COMMITTED,
    BZ_APPEND_NOT_COMMITTED,
} bz_append_state_t;

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
static uint32_t s_leading_gap;
static uint32_t s_reconcile_cursor;
static uint32_t s_reconcile_scanned;
static uint32_t s_cleanup_cursor;
static uint32_t s_cleanup_remaining;
static uint32_t s_consume_cursor, s_consume_slots;
static uint32_t s_consume_targets[BZ_PEEK_SNAPSHOT_MAX];
static uint8_t s_consume_target_count, s_consume_target_index;
static uint32_t s_consume_first_sequence;
static uint8_t s_consume_count;
static bool s_consume_complete;
static uint32_t s_consume_head, s_consume_remaining, s_consume_span;
static uint32_t s_rollover_cursor;
static uint32_t s_rollover_scanned;
static uint32_t s_pending_head, s_pending_count, s_pending_span;
static uint32_t s_pending_next, s_pending_next_sequence;
static bool s_resume_reconcile;
static bool s_old_format_seen;
static uint32_t s_peek_slots[BZ_PEEK_SNAPSHOT_MAX];
static uint32_t s_peek_first_sequence, s_peek_after_slot, s_peek_used_slots;
static uint8_t s_peek_count;
static bz_append_state_t s_append_state;
static blind_zone_record_t s_append_record;
static uint32_t s_append_sequence;
static bool s_have_last_record;
static uint32_t s_allocated_event_id;
static blind_zone_record_t s_last_record;

uint32_t blind_zone_allocate_event_id(void)
{
    if (!blind_zone_ready()) return 0U;
    if (s_allocated_event_id == 0U && s_have_last_record)
        s_allocated_event_id = s_last_record.event_id;
    if (++s_allocated_event_id == 0U) ++s_allocated_event_id;
    return s_allocated_event_id;
}
static uint32_t s_last_record_sequence;
static uint32_t s_repair_sectors[(BZ_DATA_SECTORS + 31U) / 32U];
static uint32_t s_repair_sector;
static uint32_t s_repair_slot;
static uint32_t s_repair_image;
static uint32_t s_repair_record_count;
static uint32_t s_repair_crc;
static uint64_t s_repair_bitmap;
static uint32_t s_scratch_generation;
static bz_scratch_header_t s_scratch_header;
static bool s_scratch_payload_matches;
static bool s_scratch_victim_matches;
static bool s_repair_boot_restore;
static bz_recovery_state_t s_repair_resume;
static bool s_quarantine_pending;
static blind_zone_diagnostics_t s_diagnostics;

static bz_meta_result_t commit_meta_locked(uint32_t head, uint32_t count,
                                           uint32_t span, uint32_t next,
                                           uint32_t next_sequence);

static void saturating_increment(uint32_t *counter)
{
    if (*counter != 0xffffffffUL) ++*counter;
}

void blind_zone_get_diagnostics(blind_zone_diagnostics_t *out)
{
    if (out != NULL) *out = s_diagnostics;
}

static void start_repair_locked(uint32_t sector, bz_recovery_state_t resume);

#ifdef BLIND_ZONE_TEST
void blind_zone_test_set_diagnostics(const blind_zone_diagnostics_t *value)
{
    if (value != NULL) s_diagnostics = *value;
}

blind_zone_test_recovery_state_t blind_zone_test_recovery_state(void)
{
    if (s_recovery == BZ_RECOVERY_ROLLOVER_SCAN)
        return BLIND_ZONE_TEST_RECOVERY_ROLLOVER_SCAN;
    if (s_recovery == BZ_RECOVERY_ROLLOVER_ERASE)
        return BLIND_ZONE_TEST_RECOVERY_ROLLOVER_ERASE;
    if (s_recovery == BZ_RECOVERY_REPAIR_BACKUP)
        return BLIND_ZONE_TEST_RECOVERY_SCRATCH_BACKUP;
    if (s_recovery == BZ_RECOVERY_REPAIR_HEADER ||
        s_recovery == BZ_RECOVERY_REPAIR_VALIDATE)
        return BLIND_ZONE_TEST_RECOVERY_SCRATCH_HEADER;
    if (s_recovery == BZ_RECOVERY_REPAIR_VICTIM_ERASE)
        return BLIND_ZONE_TEST_RECOVERY_VICTIM_ERASE;
    if (s_recovery == BZ_RECOVERY_REPAIR_RESTORE ||
        s_recovery == BZ_RECOVERY_REPAIR_VERIFY)
        return BLIND_ZONE_TEST_RECOVERY_VICTIM_RESTORE;
    if (s_recovery == BZ_RECOVERY_REPAIR_FINAL_ERASE)
        return BLIND_ZONE_TEST_RECOVERY_SCRATCH_ERASE;
    return BLIND_ZONE_TEST_RECOVERY_OTHER;
}

void blind_zone_test_set_state(uint32_t head, uint32_t count, uint32_t span,
                               uint32_t next, uint32_t next_sequence)
{
    s_head_slot = head;
    s_count = count;
    s_span = span;
    s_next_slot = next;
    s_next_sequence = next_sequence;
    s_recovery = BZ_RECOVERY_READY;
}

void blind_zone_test_begin_reconcile(void)
{
    s_reconcile_cursor = s_next_slot;
    s_reconcile_scanned = 0U;
    s_recovery = BZ_RECOVERY_RECONCILE;
}

void blind_zone_test_start_repair(uint32_t slot)
{
    start_repair_locked(slot / BZ_DATA_PER_SECTOR, BZ_RECOVERY_READY);
}

#endif

static bool same_append_record(const blind_zone_record_t *record)
{
    return record->event_id == s_append_record.event_id &&
           record->length == s_append_record.length &&
           memcmp(record->location, s_append_record.location, record->length) == 0;
}

static bool same_public_record(const blind_zone_record_t *left,
                               const blind_zone_record_t *right)
{
    return left->event_id == right->event_id && left->length == right->length &&
           memcmp(left->location, right->location, left->length) == 0;
}

static void begin_append_transaction(const blind_zone_record_t *record)
{
    s_append_record = *record;
    s_append_sequence = s_next_sequence;
    s_append_state = BZ_APPEND_UNCERTAIN;
}

static void confirm_append_if_sequence(uint32_t next_sequence)
{
    if (s_append_state == BZ_APPEND_UNCERTAIN &&
        next_sequence == s_append_sequence + 1U)
        s_append_state = BZ_APPEND_COMMITTED;
}

static void begin_reconcile(void)
{
    s_reconcile_cursor = s_next_slot;
    s_reconcile_scanned = 0U;
    s_recovery = BZ_RECOVERY_RECONCILE;
}


static bool sequence_newer(uint32_t candidate, uint32_t reference)
{
    return (int32_t)(candidate - reference) > 0;
}

static uint32_t record_addr(uint32_t slot)
{
    return BZ_DATA_ADDR + slot * BZ_RECORD_BYTES;
}

static bool flash_record_valid(const bz_flash_record_t *record);
static bool flash_record_body_valid(const bz_flash_record_t *record);
static bz_slot_status_t classify_record(const bz_flash_record_t *record);
static bool slot_erased(const bz_flash_record_t *record);
static bool read_record_locked(uint32_t slot, bz_flash_record_t *record);
static bool sequence_in_state(uint32_t sequence, uint32_t count,
                              uint32_t next_sequence);
static uint32_t advance_to_sequence_locked(uint32_t slot, uint32_t span,
                                           uint32_t target_sequence,
                                           uint32_t *used_out);
static bool quarantine_missing_head_locked(bz_recovery_state_t resume);

static bool bytes_erased(const void *data, uint32_t length)
{
    const uint8_t *bytes = (const uint8_t *)data;
    uint32_t i;
    for (i = 0U; i < length; ++i)
        if (bytes[i] != 0xffU) return false;
    return true;
}

static uint32_t bitmap_count(uint64_t bitmap)
{
    uint32_t count = 0U;
    while (bitmap != 0U) {
        count += (uint32_t)(bitmap & 1U);
        bitmap >>= 1;
    }
    return count;
}

static bool scratch_header_valid(const bz_scratch_header_t *header)
{
    return header->magic == BZ_SCRATCH_MAGIC &&
           header->version == BZ_FORMAT_VERSION &&
           header->header_size == sizeof(*header) &&
           header->victim_sector < BZ_DATA_SECTORS &&
           header->record_count <= BZ_DATA_PER_SECTOR - 1U &&
           header->record_count == bitmap_count(header->slot_bitmap) &&
           header->header_crc32 ==
               crc32_compute(header, (uint32_t)offsetof(bz_scratch_header_t,
                                                       header_crc32)) &&
           header->commit_marker == BZ_COMMIT_MARKER;
}

static void mark_repair_sector(uint32_t sector)
{
    if (sector < BZ_DATA_SECTORS)
        s_repair_sectors[sector / 32U] |= 1UL << (sector % 32U);
}

static void mark_repair_slot(uint32_t slot)
{
    if (slot < BLIND_ZONE_PHYSICAL_SLOTS)
        mark_repair_sector(slot / BZ_DATA_PER_SECTOR);
}

static bool next_repair_sector(uint32_t *sector_out)
{
    uint32_t sector;
    for (sector = 0U; sector < BZ_DATA_SECTORS; ++sector) {
        if ((s_repair_sectors[sector / 32U] &
             (1UL << (sector % 32U))) != 0U) {
            if (sector_out != NULL) *sector_out = sector;
            return true;
        }
    }
    return false;
}

static void clear_repair_sector(uint32_t sector)
{
    if (sector < BZ_DATA_SECTORS)
        s_repair_sectors[sector / 32U] &= ~(1UL << (sector % 32U));
}

static bool record_logically_live(const bz_flash_record_t *record)
{
    return flash_record_valid(record) &&
           sequence_in_state(record->sequence, s_count, s_next_sequence);
}

static bool record_repair_preserve(const bz_flash_record_t *record)
{
    return record_logically_live(record) ||
           (classify_record(record) == BZ_SLOT_PREPARED &&
            record->sequence == s_next_sequence);
}

static void start_repair_locked(uint32_t sector, bz_recovery_state_t resume)
{
    s_repair_sector = sector;
    s_repair_slot = 0U;
    s_repair_image = 0U;
    s_repair_record_count = 0U;
    s_repair_crc = 0xffffffffUL;
    s_repair_bitmap = 0U;
    s_repair_boot_restore = false;
    s_repair_resume = resume;
    s_recovery = BZ_RECOVERY_REPAIR_BEGIN_ERASE;
}

static bool finish_maintenance_locked(bz_recovery_state_t resume)
{
    bz_flash_record_t next;
    uint32_t sector;
    if (!read_record_locked(s_next_slot, &next)) {
        saturating_increment(&s_diagnostics.recovery_retry);
        return false;
    }
    if (!slot_erased(&next)) {
        bz_slot_status_t status = classify_record(&next);
        if (status == BZ_SLOT_ACTIVE || status == BZ_SLOT_PREPARED) {
            begin_reconcile();
            return false;
        }
        mark_repair_slot(s_next_slot);
    }
    if (next_repair_sector(&sector)) {
        start_repair_locked(sector, resume);
        return false;
    }
    if (s_quarantine_pending) return quarantine_missing_head_locked(resume);
    s_recovery = resume;
    return true;
}

/* A repaired damaged slot has no recoverable sequence bytes.  It remains in
 * the logical span until it reaches the FIFO head; only then can a durable
 * one-record quarantine advance the contiguous public sequence. */
static bool quarantine_missing_head_locked(bz_recovery_state_t resume)
{
    bz_flash_record_t head_record;
    uint32_t expected;
    uint32_t skipped;
    uint32_t next_head;
    if (s_count == 0U) {
        s_recovery = resume;
        return true;
    }
    expected = s_next_sequence - s_count;
    if (!read_record_locked(s_head_slot, &head_record)) {
        saturating_increment(&s_diagnostics.recovery_retry);
        return false;
    }
    if (flash_record_valid(&head_record) && head_record.sequence == expected) {
        s_quarantine_pending = false;
        s_recovery = resume;
        return true;
    }
    if (s_count == 1U) {
        next_head = s_next_slot;
        skipped = s_span;
    } else {
        next_head = advance_to_sequence_locked(s_head_slot, s_span,
                                               expected + 1U, &skipped);
        if (next_head >= BLIND_ZONE_PHYSICAL_SLOTS) {
            saturating_increment(&s_diagnostics.recovery_retry);
            return false;
        }
    }
    if (commit_meta_locked(next_head, s_count - 1U, s_span - skipped,
                           s_next_slot, s_next_sequence) != BZ_META_OK) {
        saturating_increment(&s_diagnostics.recovery_retry);
        return false;
    }
    saturating_increment(&s_diagnostics.corrupt_quarantine);
    return quarantine_missing_head_locked(resume);
}

static void request_head_quarantine_if_missing_locked(void)
{
    bz_flash_record_t record;
    uint32_t expected;
    if (s_count == 0U || s_head_slot / BZ_DATA_PER_SECTOR != s_repair_sector)
        return;
    expected = s_next_sequence - s_count;
    if (!read_record_locked(s_head_slot, &record)) {
        saturating_increment(&s_diagnostics.recovery_retry);
        return;
    }
    if (!flash_record_valid(&record) || record.sequence != expected)
        s_quarantine_pending = true;
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
    return meta->crc32 == crc32_compute(meta, (uint32_t)offsetof(bz_meta_t, crc32));
}

static bool meta_is_old_format(const bz_meta_t *meta)
{
    return meta->magic == BZ_META_MAGIC && meta->version != BZ_FORMAT_VERSION &&
           meta->commit_marker == BZ_COMMIT_MARKER;
}

static bool flash_record_body_valid(const bz_flash_record_t *record)
{
    if (record->magic != BZ_RECORD_MAGIC || record->version != BZ_FORMAT_VERSION ||
        record->event_id == 0U || record->length > BLIND_ZONE_LOCATION_MAX)
        return false;
    return record->crc32 == crc32_compute(record, (uint32_t)offsetof(bz_flash_record_t, crc32));
}

static bool flash_record_is_old_format(const bz_flash_record_t *record)
{
    return record->magic == BZ_RECORD_MAGIC && record->version != BZ_FORMAT_VERSION &&
           record->commit_marker == BZ_COMMIT_MARKER;
}

static bz_slot_status_t classify_record(const bz_flash_record_t *record)
{
    uint32_t marker;
    if (slot_erased(record)) return BZ_SLOT_ERASED;
    if (record->magic == BZ_RECORD_MAGIC && record->version != BZ_FORMAT_VERSION)
        return BZ_SLOT_OLD_FORMAT;
    if (!flash_record_body_valid(record)) return BZ_SLOT_DAMAGED;
    marker = record->commit_marker;
    if (marker == BZ_COMMIT_MARKER) return BZ_SLOT_ACTIVE;
    if ((marker & BZ_COMMIT_MARKER) == BZ_COMMIT_MARKER)
        return BZ_SLOT_PREPARED;
    if ((marker & BZ_COMMIT_MARKER) == marker)
        return BZ_SLOT_CONSUMED;
    return BZ_SLOT_DAMAGED;
}

static bool flash_record_valid(const bz_flash_record_t *record)
{
    return classify_record(record) == BZ_SLOT_ACTIVE;
}

static void cache_flash_record(const bz_flash_record_t *record)
{
    if (!flash_record_body_valid(record)) return;
    if (!s_have_last_record || sequence_newer(record->sequence, s_last_record_sequence) ||
        record->sequence == s_last_record_sequence) {
        s_last_record.event_id = record->event_id;
        s_last_record.length = (uint8_t)record->length;
        memcpy(s_last_record.location, record->location, record->length);
        if (record->length < BLIND_ZONE_LOCATION_MAX)
            memset(s_last_record.location + record->length, 0,
                   BLIND_ZONE_LOCATION_MAX - record->length);
        s_last_record_sequence = record->sequence;
        s_have_last_record = true;
    }
}

static void cache_public_record(const blind_zone_record_t *record, uint32_t sequence)
{
    s_last_record = *record;
    s_last_record_sequence = sequence;
    s_have_last_record = true;
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
        if (!read_record_locked(slot, &record)) {
            saturating_increment(&s_diagnostics.append_io);
            return true;
        }
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

static bz_meta_result_t adopt_record_locked(uint32_t record_slot, uint32_t span)
{
    uint32_t head = s_head_slot;
    uint32_t count = s_count;
    if (count == BLIND_ZONE_LOGICAL_CAPACITY) {
        uint32_t skipped;
        uint32_t new_head = advance_to_sequence_locked(
            head, span, s_next_sequence - count + 1U, &skipped);
        if (new_head >= BLIND_ZONE_PHYSICAL_SLOTS) return BZ_META_ERROR;
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

static bool sequence_in_state(uint32_t sequence, uint32_t count, uint32_t next_sequence)
{
    uint32_t first = next_sequence - count;
    if (count == 0U) return false;
    return (uint32_t)(sequence - first) < count;
}

static void schedule_rollover(uint32_t head, uint32_t count, uint32_t span,
                              uint32_t next, uint32_t next_sequence)
{
    s_pending_head = head; s_pending_count = count; s_pending_span = span;
    s_pending_next = next; s_pending_next_sequence = next_sequence;
    s_rollover_cursor = 0U; s_rollover_scanned = 0U;
    s_recovery = BZ_RECOVERY_ROLLOVER_SCAN;
}

static bz_meta_result_t write_meta_locked(uint32_t head, uint32_t count,
                                          uint32_t span, uint32_t next,
                                          uint32_t next_sequence)
{
    bz_meta_t meta;
    uint32_t commit = BZ_COMMIT_MARKER;
    uint32_t address;
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
    meta.crc32 = crc32_compute(&meta, (uint32_t)offsetof(bz_meta_t, crc32));
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
        return BZ_META_ERROR;
    }
    s_generation = meta.generation;
    ++s_meta_next_slot;
    apply_state(head, count, span, next, next_sequence);
    return BZ_META_OK;
}

static bz_meta_result_t commit_meta_locked(uint32_t head, uint32_t count,
                                           uint32_t span, uint32_t next,
                                           uint32_t next_sequence)
{
    if (s_meta_next_slot >= BZ_META_ENTRIES) {
        schedule_rollover(head, count, span, next, next_sequence);
        return BZ_META_PENDING;
    }
    return write_meta_locked(head, count, span, next, next_sequence);
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
    bz_slot_status_t status = classify_record(record);
    bz_flash_record_t finalized;
    if (flash_record_is_old_format(record)) s_old_format_seen = true;
    if (status == BZ_SLOT_DAMAGED) mark_repair_slot(slot);
    if (status == BZ_SLOT_PREPARED) {
        uint32_t commit = BZ_COMMIT_MARKER;
        if (!ext_flash_write_verified(EXT_FLASH_OWNER_BLIND_ZONE,
                record_addr(slot) + offsetof(bz_flash_record_t, commit_marker),
                &commit, sizeof(commit))) {
            saturating_increment(&s_diagnostics.recovery_retry);
            mark_repair_slot(slot);
            return;
        }
        if (!read_record_locked(slot, &finalized)) {
            saturating_increment(&s_diagnostics.recovery_retry);
            mark_repair_slot(slot);
            return;
        }
        record = &finalized;
    }
    if (!flash_record_valid(record)) {
        if (s_current_run.valid) ++s_current_run.gap;
        else if (!s_first_run.valid) ++s_leading_gap;
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

static void scan_repair_record(uint32_t slot, const bz_flash_record_t *record)
{
    bz_slot_status_t status = classify_record(record);
    if (flash_record_is_old_format(record)) s_old_format_seen = true;
    if (status == BZ_SLOT_DAMAGED) mark_repair_slot(slot);
    if (status == BZ_SLOT_PREPARED) {
        uint32_t commit = BZ_COMMIT_MARKER;
        if (!ext_flash_write_verified(EXT_FLASH_OWNER_BLIND_ZONE,
                record_addr(slot) + offsetof(bz_flash_record_t, commit_marker),
                &commit, sizeof(commit))) {
            saturating_increment(&s_diagnostics.recovery_retry);
            mark_repair_slot(slot);
        } else {
            bz_flash_record_t finalized;
            if (!read_record_locked(slot, &finalized) ||
                !flash_record_valid(&finalized))
                mark_repair_slot(slot);
        }
    }
}

static void complete_data_scan(void)
{
    bz_run_t merged;
    if (s_old_format_seen) {
        saturating_increment(&s_diagnostics.format_rejected);
        s_recovery = BZ_RECOVERY_IDLE;
        return;
    }
    finish_current_run();
    if (s_first_run.valid && s_last_run.valid &&
        s_first_run.first_slot != s_last_run.first_slot &&
        s_first_run.first_sequence == s_last_run.last_sequence + 1U) {
        merged = s_last_run;
        merged.last_slot = s_first_run.last_slot;
        merged.last_sequence = s_first_run.last_sequence;
        merged.length += s_first_run.length;
        merged.span = s_last_run.span + s_last_run.gap + s_leading_gap +
                      s_first_run.span;
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
    s_recovery = BZ_RECOVERY_SCRATCH_CHECK;
    s_meta_scan_slot = 0U;
    s_meta_next_slot = 0U;
    s_have_meta = false;
    memset(&s_best_meta, 0, sizeof(s_best_meta));
    s_data_scan_slot = 0U;
    memset(&s_current_run, 0, sizeof(s_current_run));
    memset(&s_first_run, 0, sizeof(s_first_run));
    memset(&s_last_run, 0, sizeof(s_last_run));
    memset(&s_best_run, 0, sizeof(s_best_run));
    s_leading_gap = 0U;
    s_reconcile_cursor = 0U;
    s_reconcile_scanned = 0U;
    s_cleanup_cursor = 0U;
    s_cleanup_remaining = 0U;
    s_consume_cursor = 0U;
    s_consume_slots = 0U;
    s_consume_first_sequence = 0U;
    s_consume_count = 0U;
    s_consume_complete = false;
    s_consume_target_count = 0U;
    s_consume_target_index = 0U;
    s_rollover_cursor = 0U;
    s_rollover_scanned = 0U;
    s_resume_reconcile = false;
    s_old_format_seen = false;
    s_peek_count = 0U;
    s_append_state = BZ_APPEND_NONE;
    s_append_sequence = 0U;
    s_have_last_record = false;
    s_allocated_event_id = 0U;
    s_last_record_sequence = 0U;
    memset(s_repair_sectors, 0, sizeof(s_repair_sectors));
    s_repair_sector = 0U;
    s_repair_slot = 0U;
    s_repair_image = 0U;
    s_repair_record_count = 0U;
    s_repair_crc = 0xffffffffUL;
    s_repair_bitmap = 0U;
    s_scratch_generation = 0U;
    memset(&s_scratch_header, 0, sizeof(s_scratch_header));
    s_scratch_payload_matches = false;
    s_scratch_victim_matches = false;
    s_repair_boot_restore = false;
    s_quarantine_pending = false;
    s_repair_resume = BZ_RECOVERY_META;
    apply_state(0U, 0U, 0U, 0U, 1U);
    s_generation = 0U;
    return true;
}

bool blind_zone_ready(void)
{
    return s_recovery == BZ_RECOVERY_READY;
}

/* Each step requires the BLIND_ZONE owner held by the dispatcher. Steps
 * retain their original per-call scan budget and never release that owner.
 * State changes take effect on the NEXT process call, not within this dispatch.
 * Force these source-only boundaries inline: ordinary extraction lets -Os/LTO
 * inline the dispatcher into main and retain selected steps out of line,
 * changing code size and stack/layout. Keep the original machine-code boundary.
 * Transition/side-effect table: docs/arch01-state-audit-20260915.md. */
static inline __attribute__((always_inline)) void recovery_scratch_check_locked(void)
{
    if (!ext_flash_read(EXT_FLASH_OWNER_BLIND_ZONE, BZ_SCRATCH_ADDR,
                        &s_scratch_header, sizeof(s_scratch_header))) {
        saturating_increment(&s_diagnostics.recovery_retry);
    } else if (bytes_erased(&s_scratch_header, sizeof(s_scratch_header))) {
        s_recovery = BZ_RECOVERY_META;
    } else if (scratch_header_valid(&s_scratch_header)) {
        s_repair_sector = s_scratch_header.victim_sector;
        s_repair_image = 0U;
        s_repair_crc = 0xffffffffUL;
        s_scratch_payload_matches = false;
        s_scratch_victim_matches = false;
        s_repair_boot_restore = true;
        s_recovery = BZ_RECOVERY_SCRATCH_VALIDATE;
    } else {
        s_recovery = BZ_RECOVERY_SCRATCH_DISCARD;
    }
}

static inline __attribute__((always_inline)) void recovery_scratch_validate_locked(void)
{
    uint32_t reads = 0U;
    while (reads < BZ_RECOVERY_READS &&
           s_repair_image < s_scratch_header.record_count) {
        bz_flash_record_t image;
        if (!ext_flash_read(EXT_FLASH_OWNER_BLIND_ZONE,
                            BZ_SCRATCH_ADDR +
                                (s_repair_image + 1U) * BZ_RECORD_BYTES,
                            &image, sizeof(image))) {
            saturating_increment(&s_diagnostics.recovery_retry);
            break;
        }
        if (!flash_record_valid(&image)) {
            s_scratch_payload_matches = false;
            s_recovery = BZ_RECOVERY_SCRATCH_DISCARD;
            break;
        }
        s_repair_crc = crc32_update(s_repair_crc, &image, sizeof(image));
        ++s_repair_image;
        ++reads;
    }
    if (s_repair_image == s_scratch_header.record_count) {
        s_scratch_payload_matches =
            (s_repair_crc ^ 0xffffffffUL) ==
                s_scratch_header.payload_crc32;
        s_repair_slot = 0U;
        s_repair_crc = 0xffffffffUL;
        s_recovery = BZ_RECOVERY_SCRATCH_VICTIM_VALIDATE;
    }
}

static inline __attribute__((always_inline)) void recovery_scratch_victim_validate_locked(void)
{
    uint32_t reads = 0U;
    while (reads < BZ_RECOVERY_READS &&
           s_repair_slot < BZ_DATA_PER_SECTOR) {
        if ((s_scratch_header.slot_bitmap &
             ((uint64_t)1U << s_repair_slot)) != 0U) {
            bz_flash_record_t image;
            uint32_t slot = s_repair_sector * BZ_DATA_PER_SECTOR +
                            s_repair_slot;
            if (!read_record_locked(slot, &image)) {
                saturating_increment(&s_diagnostics.recovery_retry);
                break;
            }
            s_repair_crc = crc32_update(s_repair_crc, &image, sizeof(image));
        }
        ++s_repair_slot;
        ++reads;
    }
    if (s_repair_slot == BZ_DATA_PER_SECTOR) {
        s_scratch_victim_matches =
            (s_repair_crc ^ 0xffffffffUL) ==
                s_scratch_header.payload_crc32;
        if (s_scratch_payload_matches) {
            s_repair_image = 0U;
            s_recovery = BZ_RECOVERY_REPAIR_VICTIM_ERASE;
        } else if (s_scratch_victim_matches) {
            s_recovery = BZ_RECOVERY_SCRATCH_DISCARD;
        } else {
            saturating_increment(&s_diagnostics.format_rejected);
            s_recovery = BZ_RECOVERY_IDLE;
        }
    }
}

static inline __attribute__((always_inline)) void recovery_scratch_discard_locked(void)
{
    if (ext_flash_erase(EXT_FLASH_OWNER_BLIND_ZONE, BZ_SCRATCH_ADDR,
                        FLASH_SECTOR_SIZE))
        s_recovery = BZ_RECOVERY_META;
    else
        saturating_increment(&s_diagnostics.recovery_retry);
}

static inline __attribute__((always_inline)) void recovery_meta_locked(void)
{
    uint32_t reads = 0U;
    while (reads++ < BZ_RECOVERY_READS && s_meta_scan_slot < BZ_META_ENTRIES) {
        bz_meta_t meta;
        if (!ext_flash_read(EXT_FLASH_OWNER_BLIND_ZONE,
                            EXT_FLASH_BLIND_ADDR + s_meta_scan_slot * BZ_META_BYTES,
                            &meta, sizeof(meta))) {
            saturating_increment(&s_diagnostics.recovery_retry);
            break;
        }
        if (meta_is_old_format(&meta)) s_old_format_seen = true;
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
            s_data_scan_slot = 0U;
            s_recovery = BZ_RECOVERY_DATA;
        } else if (s_old_format_seen) {
            saturating_increment(&s_diagnostics.format_rejected);
            s_recovery = BZ_RECOVERY_IDLE;
        } else {
            s_recovery = BZ_RECOVERY_DATA;
        }
    }
}

static inline __attribute__((always_inline)) void recovery_data_locked(void)
{
    uint32_t reads = 0U;
    while (reads++ < BZ_RECOVERY_READS &&
           s_data_scan_slot < BLIND_ZONE_PHYSICAL_SLOTS) {
        bz_flash_record_t record;
        if (!read_record_locked(s_data_scan_slot, &record)) {
            saturating_increment(&s_diagnostics.recovery_retry);
            break;
        }
        if (s_have_meta) scan_repair_record(s_data_scan_slot, &record);
        else scan_record(s_data_scan_slot, &record);
        ++s_data_scan_slot;
    }
    if (s_data_scan_slot == BLIND_ZONE_PHYSICAL_SLOTS) {
        if (s_have_meta) {
            uint32_t sector;
            if (s_old_format_seen) {
                saturating_increment(&s_diagnostics.format_rejected);
                s_recovery = BZ_RECOVERY_IDLE;
            } else if (next_repair_sector(&sector)) {
                start_repair_locked(sector, BZ_RECOVERY_RECONCILE);
            } else {
                begin_reconcile();
            }
        } else {
            complete_data_scan();
        }
    }
}

static inline __attribute__((always_inline)) void recovery_reconcile_locked(void)
{
    uint32_t reads = 0U;
    while (reads < BZ_RECOVERY_READS &&
           s_reconcile_scanned < BLIND_ZONE_PHYSICAL_SLOTS) {
        bz_flash_record_t record;
        uint32_t adopted_span;
        if (!read_record_locked(s_reconcile_cursor, &record)) {
            saturating_increment(&s_diagnostics.recovery_retry);
            break;
        }
        if (classify_record(&record) == BZ_SLOT_PREPARED &&
            record.sequence == s_next_sequence) {
            uint32_t commit = BZ_COMMIT_MARKER;
            if (!ext_flash_write_verified(EXT_FLASH_OWNER_BLIND_ZONE,
                    record_addr(s_reconcile_cursor) +
                        offsetof(bz_flash_record_t, commit_marker),
                    &commit, sizeof(commit)) ||
                !read_record_locked(s_reconcile_cursor, &record)) {
                saturating_increment(&s_diagnostics.recovery_retry);
                mark_repair_slot(s_reconcile_cursor);
                break;
            }
        }
        adopted_span = s_span + s_reconcile_scanned + 1U;
        if (flash_record_valid(&record) &&
            sequence_in_state(record.sequence, s_count, s_next_sequence) &&
            (!s_have_last_record ||
             sequence_newer(record.sequence, s_last_record_sequence)))
            cache_flash_record(&record);
        if (flash_record_valid(&record) &&
            record.sequence == s_next_sequence &&
            adopted_span <= BLIND_ZONE_PHYSICAL_SLOTS) {
            bz_meta_result_t adopted =
                adopt_record_locked(s_reconcile_cursor, adopted_span);
            if (adopted == BZ_META_OK) {
                confirm_append_if_sequence(s_next_sequence);
                begin_reconcile();
            }
            else if (adopted == BZ_META_PENDING) {
                s_resume_reconcile = true;
                saturating_increment(&s_diagnostics.pending_reconciliation);
            } else saturating_increment(&s_diagnostics.recovery_retry);
            break;
        }
        s_reconcile_cursor =
            (s_reconcile_cursor + 1U) % BLIND_ZONE_PHYSICAL_SLOTS;
        ++s_reconcile_scanned;
        ++reads;
    }
    if (s_reconcile_scanned == BLIND_ZONE_PHYSICAL_SLOTS) {
        bz_flash_record_t stale_next;
        uint32_t consumed = BZ_RECORD_CONSUMED;
        if (s_append_state == BZ_APPEND_UNCERTAIN)
            s_append_state = BZ_APPEND_NOT_COMMITTED;
        if (s_span == BLIND_ZONE_PHYSICAL_SLOTS &&
            read_record_locked(s_next_slot, &stale_next) &&
            (classify_record(&stale_next) == BZ_SLOT_ACTIVE ||
             classify_record(&stale_next) == BZ_SLOT_PREPARED) &&
            !sequence_in_state(stale_next.sequence, s_count,
                               s_next_sequence)) {
            if (ext_flash_write_verified(
                    EXT_FLASH_OWNER_BLIND_ZONE,
                    record_addr(s_next_slot) +
                        offsetof(bz_flash_record_t, commit_marker),
                    &consumed, sizeof(consumed))) {
                mark_repair_slot(s_next_slot);
                start_repair_locked(s_next_slot / BZ_DATA_PER_SECTOR,
                                    BZ_RECOVERY_READY);
            } else {
                saturating_increment(&s_diagnostics.recovery_retry);
            }
        } else {
            (void)finish_maintenance_locked(BZ_RECOVERY_READY);
        }
    }
}

static inline __attribute__((always_inline)) void recovery_finalize_locked(void)
{
    bz_meta_result_t committed =
        commit_meta_locked(s_head_slot, s_count, s_span,
                           s_next_slot, s_next_sequence);
    if (committed == BZ_META_OK)
        (void)finish_maintenance_locked(BZ_RECOVERY_READY);
    else if (committed == BZ_META_ERROR)
        saturating_increment(&s_diagnostics.recovery_retry);
}

static inline __attribute__((always_inline)) void recovery_cleanup_locked(void)
{
    uint32_t reads = 0U;
    while (reads < BZ_RECOVERY_READS && s_cleanup_remaining != 0U) {
        bz_flash_record_t record;
        uint32_t consumed = BZ_RECORD_CONSUMED;
        if (!read_record_locked(s_cleanup_cursor, &record)) {
            saturating_increment(&s_diagnostics.recovery_retry);
            break;
        }
        if (flash_record_valid(&record) &&
            !sequence_in_state(record.sequence, s_count, s_next_sequence) &&
            !ext_flash_write_verified(EXT_FLASH_OWNER_BLIND_ZONE,
                record_addr(s_cleanup_cursor) + offsetof(bz_flash_record_t, commit_marker),
                &consumed, sizeof(consumed)))
        {
            saturating_increment(&s_diagnostics.recovery_retry);
            break;
        }
        s_cleanup_cursor = (s_cleanup_cursor + 1U) % BLIND_ZONE_PHYSICAL_SLOTS;
        --s_cleanup_remaining;
        ++reads;
    }
    if (s_cleanup_remaining == 0U)
        (void)finish_maintenance_locked(BZ_RECOVERY_READY);
}

static inline __attribute__((always_inline)) void recovery_consume_locked(void)
{
    uint32_t reads = 0U;
    while (reads < BZ_RECOVERY_READS &&
           s_consume_target_index < s_consume_target_count) {
        bz_flash_record_t record;
        uint32_t consumed = BZ_RECORD_CONSUMED;
        uint32_t target = s_consume_targets[s_consume_target_index];
        if (!read_record_locked(target, &record)) {
            saturating_increment(&s_diagnostics.consume_io);
            saturating_increment(&s_diagnostics.recovery_retry);
            break;
        }
        if (record.commit_marker == BZ_COMMIT_MARKER &&
            !ext_flash_write_verified(EXT_FLASH_OWNER_BLIND_ZONE,
                record_addr(target) + offsetof(bz_flash_record_t, commit_marker),
                &consumed, sizeof(consumed)))
        {
            saturating_increment(&s_diagnostics.consume_io);
            saturating_increment(&s_diagnostics.recovery_retry);
            break;
        }
        ++s_consume_target_index;
        ++reads;
    }
    if (s_consume_target_index == s_consume_target_count)
        s_recovery = BZ_RECOVERY_CONSUME_META;
}

static inline __attribute__((always_inline)) void recovery_consume_meta_locked(void)
{
    bz_meta_result_t committed = commit_meta_locked(
        s_consume_head, s_consume_remaining, s_consume_span,
        s_next_slot, s_next_sequence);
    if (committed == BZ_META_OK) {
        s_consume_complete = true;
        /* Keep a peek-detected middle hole deferred until it reaches the
         * public head and a later peek explicitly requests maintenance. */
        (void)finish_maintenance_locked(BZ_RECOVERY_READY);
    } else if (committed == BZ_META_PENDING) {
        s_resume_reconcile = false;
    } else saturating_increment(&s_diagnostics.recovery_retry);
}

static inline __attribute__((always_inline)) void recovery_rollover_scan_locked(void)
{
    uint32_t reads = 0U;
    while (reads < BZ_RECOVERY_READS &&
           s_rollover_scanned < BLIND_ZONE_PHYSICAL_SLOTS) {
        bz_flash_record_t record;
        uint32_t consumed = BZ_RECORD_CONSUMED;
        if (!read_record_locked(s_rollover_cursor, &record)) {
            saturating_increment(&s_diagnostics.recovery_retry);
            break;
        }
        if (flash_record_valid(&record) &&
            !sequence_in_state(record.sequence, s_pending_count,
                               s_pending_next_sequence) &&
            !ext_flash_write_verified(EXT_FLASH_OWNER_BLIND_ZONE,
                record_addr(s_rollover_cursor) + offsetof(bz_flash_record_t, commit_marker),
                &consumed, sizeof(consumed)))
        {
            saturating_increment(&s_diagnostics.recovery_retry);
            break;
        }
        s_rollover_cursor =
            (s_rollover_cursor + 1U) % BLIND_ZONE_PHYSICAL_SLOTS;
        ++s_rollover_scanned;
        ++reads;
    }
    if (s_rollover_scanned == BLIND_ZONE_PHYSICAL_SLOTS)
        s_recovery = BZ_RECOVERY_ROLLOVER_ERASE;
}

static inline __attribute__((always_inline)) void recovery_rollover_erase_locked(void)
{
    if (ext_flash_erase(EXT_FLASH_OWNER_BLIND_ZONE, EXT_FLASH_BLIND_ADDR,
                        FLASH_SECTOR_SIZE)) {
        s_meta_next_slot = 0U;
        if (write_meta_locked(s_pending_head, s_pending_count, s_pending_span,
                              s_pending_next, s_pending_next_sequence) == BZ_META_OK) {
            apply_state(s_pending_head, s_pending_count, s_pending_span,
                        s_pending_next, s_pending_next_sequence);
            confirm_append_if_sequence(s_pending_next_sequence);
            if (s_consume_count != 0U &&
                s_pending_head == s_consume_head &&
                s_pending_count == s_consume_remaining) {
                s_consume_complete = true;
                (void)finish_maintenance_locked(BZ_RECOVERY_READY);
            } else if (s_resume_reconcile) {
                s_resume_reconcile = false;
                begin_reconcile();
            } else {
                (void)finish_maintenance_locked(BZ_RECOVERY_READY);
            }
        } else saturating_increment(&s_diagnostics.recovery_retry);
    } else saturating_increment(&s_diagnostics.recovery_retry);
}

static inline __attribute__((always_inline)) void recovery_repair_begin_erase_locked(void)
{
    if (ext_flash_erase(EXT_FLASH_OWNER_BLIND_ZONE, BZ_SCRATCH_ADDR,
                        FLASH_SECTOR_SIZE)) {
        s_repair_slot = 0U;
        s_repair_image = 0U;
        s_repair_record_count = 0U;
        s_repair_bitmap = 0U;
        s_repair_crc = 0xffffffffUL;
        s_recovery = BZ_RECOVERY_REPAIR_BACKUP;
    } else {
        saturating_increment(&s_diagnostics.recovery_retry);
    }
}

static inline __attribute__((always_inline)) void recovery_repair_backup_locked(void)
{
    uint32_t reads = 0U;
    while (reads < BZ_RECOVERY_READS && s_repair_slot < BZ_DATA_PER_SECTOR) {
        bz_flash_record_t record;
        uint32_t slot = s_repair_sector * BZ_DATA_PER_SECTOR + s_repair_slot;
        if (!read_record_locked(slot, &record)) {
            saturating_increment(&s_diagnostics.recovery_retry);
            break;
        }
        if (record_repair_preserve(&record)) {
            uint32_t image_addr = BZ_SCRATCH_ADDR +
                (s_repair_record_count + 1U) * BZ_RECORD_BYTES;
            if (s_repair_record_count >= BZ_DATA_PER_SECTOR - 1U ||
                !ext_flash_write_verified(EXT_FLASH_OWNER_BLIND_ZONE,
                                          image_addr, &record,
                                          sizeof(record))) {
                saturating_increment(&s_diagnostics.recovery_retry);
                s_recovery = BZ_RECOVERY_REPAIR_BEGIN_ERASE;
                break;
            }
            s_repair_bitmap |= (uint64_t)1U << s_repair_slot;
            s_repair_crc = crc32_update(s_repair_crc, &record, sizeof(record));
            ++s_repair_record_count;
        }
        ++s_repair_slot;
        ++reads;
    }
    if (s_repair_slot == BZ_DATA_PER_SECTOR)
        s_recovery = BZ_RECOVERY_REPAIR_HEADER;
}

static inline __attribute__((always_inline)) void recovery_repair_header_locked(void)
{
    uint32_t commit = BZ_COMMIT_MARKER;
    memset(&s_scratch_header, 0, sizeof(s_scratch_header));
    s_scratch_header.magic = BZ_SCRATCH_MAGIC;
    s_scratch_header.version = BZ_FORMAT_VERSION;
    s_scratch_header.header_size = sizeof(s_scratch_header);
    s_scratch_header.victim_sector = s_repair_sector;
    s_scratch_header.generation = ++s_scratch_generation;
    s_scratch_header.slot_bitmap = s_repair_bitmap;
    s_scratch_header.record_count = s_repair_record_count;
    s_scratch_header.payload_crc32 = s_repair_crc ^ 0xffffffffUL;
    s_scratch_header.header_crc32 = crc32_compute(
        &s_scratch_header,
        (uint32_t)offsetof(bz_scratch_header_t, header_crc32));
    s_scratch_header.commit_marker = 0xffffffffUL;
    if (!ext_flash_write_verified(EXT_FLASH_OWNER_BLIND_ZONE,
                                  BZ_SCRATCH_ADDR,
                                  &s_scratch_header,
                                  (uint32_t)offsetof(bz_scratch_header_t,
                                                     commit_marker)) ||
        !ext_flash_write_verified(EXT_FLASH_OWNER_BLIND_ZONE,
                                  BZ_SCRATCH_ADDR +
                                      offsetof(bz_scratch_header_t,
                                               commit_marker),
                                  &commit, sizeof(commit))) {
        saturating_increment(&s_diagnostics.recovery_retry);
        s_recovery = BZ_RECOVERY_REPAIR_BEGIN_ERASE;
    } else {
        s_scratch_header.commit_marker = BZ_COMMIT_MARKER;
        s_repair_image = 0U;
        s_repair_crc = 0xffffffffUL;
        s_recovery = BZ_RECOVERY_REPAIR_VALIDATE;
    }
}

static inline __attribute__((always_inline)) void recovery_repair_validate_locked(void)
{
    uint32_t reads = 0U;
    while (reads < BZ_RECOVERY_READS &&
           s_repair_image < s_repair_record_count) {
        bz_flash_record_t image;
        if (!ext_flash_read(EXT_FLASH_OWNER_BLIND_ZONE,
                            BZ_SCRATCH_ADDR +
                                (s_repair_image + 1U) * BZ_RECORD_BYTES,
                            &image, sizeof(image))) {
            saturating_increment(&s_diagnostics.recovery_retry);
            break;
        }
        if (!flash_record_valid(&image) &&
            !(classify_record(&image) == BZ_SLOT_PREPARED &&
              image.sequence == s_next_sequence)) {
            saturating_increment(&s_diagnostics.recovery_retry);
            s_recovery = BZ_RECOVERY_REPAIR_BEGIN_ERASE;
            break;
        }
        s_repair_crc = crc32_update(s_repair_crc, &image, sizeof(image));
        ++s_repair_image;
        ++reads;
    }
    if (s_repair_image == s_repair_record_count) {
        if (scratch_header_valid(&s_scratch_header) &&
            (s_repair_crc ^ 0xffffffffUL) ==
                s_scratch_header.payload_crc32) {
            s_repair_image = 0U;
            s_recovery = BZ_RECOVERY_REPAIR_VICTIM_ERASE;
        } else {
            saturating_increment(&s_diagnostics.recovery_retry);
            s_recovery = BZ_RECOVERY_REPAIR_BEGIN_ERASE;
        }
    }
}

static inline __attribute__((always_inline)) void recovery_repair_victim_erase_locked(void)
{
    uint32_t victim_addr = BZ_DATA_ADDR +
        s_repair_sector * FLASH_SECTOR_SIZE;
    if (ext_flash_erase(EXT_FLASH_OWNER_BLIND_ZONE, victim_addr,
                        FLASH_SECTOR_SIZE)) {
        s_repair_image = 0U;
        s_repair_slot = 0U;
        s_recovery = BZ_RECOVERY_REPAIR_RESTORE;
    } else {
        saturating_increment(&s_diagnostics.recovery_retry);
    }
}

static inline __attribute__((always_inline)) void recovery_repair_restore_locked(void)
{
    uint32_t reads = 0U;
    while (reads < BZ_RECOVERY_READS &&
           s_repair_image < s_scratch_header.record_count) {
        bz_flash_record_t image;
        uint32_t slot;
        while (s_repair_slot < BZ_DATA_PER_SECTOR &&
               (s_scratch_header.slot_bitmap &
                ((uint64_t)1U << s_repair_slot)) == 0U)
            ++s_repair_slot;
        if (s_repair_slot >= BZ_DATA_PER_SECTOR ||
            !ext_flash_read(EXT_FLASH_OWNER_BLIND_ZONE,
                            BZ_SCRATCH_ADDR +
                                (s_repair_image + 1U) * BZ_RECORD_BYTES,
                            &image, sizeof(image))) {
            saturating_increment(&s_diagnostics.recovery_retry);
            break;
        }
        slot = s_repair_sector * BZ_DATA_PER_SECTOR + s_repair_slot;
        if (!ext_flash_write_verified(EXT_FLASH_OWNER_BLIND_ZONE,
                                      record_addr(slot), &image,
                                      sizeof(image))) {
            saturating_increment(&s_diagnostics.recovery_retry);
            s_recovery = BZ_RECOVERY_REPAIR_VICTIM_ERASE;
            break;
        }
        ++s_repair_slot;
        ++s_repair_image;
        ++reads;
    }
    if (s_repair_image == s_scratch_header.record_count) {
        s_repair_slot = 0U;
        s_repair_image = 0U;
        s_recovery = BZ_RECOVERY_REPAIR_VERIFY;
    }
}

static inline __attribute__((always_inline)) void recovery_repair_verify_locked(void)
{
    uint32_t reads = 0U;
    while (reads < BZ_RECOVERY_READS &&
           s_repair_image < s_scratch_header.record_count) {
        bz_flash_record_t scratch_image, victim_image;
        uint32_t commit = BZ_COMMIT_MARKER;
        uint32_t slot;
        while (s_repair_slot < BZ_DATA_PER_SECTOR &&
               (s_scratch_header.slot_bitmap &
                ((uint64_t)1U << s_repair_slot)) == 0U)
            ++s_repair_slot;
        slot = s_repair_sector * BZ_DATA_PER_SECTOR + s_repair_slot;
        if (s_repair_slot >= BZ_DATA_PER_SECTOR ||
            !ext_flash_read(EXT_FLASH_OWNER_BLIND_ZONE,
                            BZ_SCRATCH_ADDR +
                                (s_repair_image + 1U) * BZ_RECORD_BYTES,
                            &scratch_image, sizeof(scratch_image)) ||
            !read_record_locked(slot, &victim_image) ||
            memcmp(&scratch_image, &victim_image,
                   sizeof(scratch_image)) != 0) {
            saturating_increment(&s_diagnostics.recovery_retry);
            s_recovery = BZ_RECOVERY_REPAIR_VICTIM_ERASE;
            break;
        }
        if (classify_record(&victim_image) == BZ_SLOT_PREPARED &&
            victim_image.sequence == s_next_sequence) {
            if (!ext_flash_write_verified(
                    EXT_FLASH_OWNER_BLIND_ZONE,
                    record_addr(slot) +
                        offsetof(bz_flash_record_t, commit_marker),
                    &commit, sizeof(commit)) ||
                !read_record_locked(slot, &victim_image) ||
                !flash_record_valid(&victim_image)) {
                saturating_increment(&s_diagnostics.recovery_retry);
                break;
            }
        }
        ++s_repair_slot;
        ++s_repair_image;
        ++reads;
    }
    if (s_repair_image == s_scratch_header.record_count)
        s_recovery = BZ_RECOVERY_REPAIR_FINAL_ERASE;
}

static inline __attribute__((always_inline)) void recovery_repair_final_erase_locked(void)
{
    if (ext_flash_erase(EXT_FLASH_OWNER_BLIND_ZONE, BZ_SCRATCH_ADDR,
                        FLASH_SECTOR_SIZE)) {
        clear_repair_sector(s_repair_sector);
        request_head_quarantine_if_missing_locked();
        if (s_repair_boot_restore) {
            s_repair_boot_restore = false;
            /* Scratch already restored the exact victim bytes.  Preserve
             * the still-valid journal; raw recovery would discard the
             * prefix before a repaired middle gap. */
            s_recovery = BZ_RECOVERY_META;
        } else if (!quarantine_missing_head_locked(s_repair_resume)) {
            /* Preserve global FIFO state during physical repair; only a
             * missing logical head is durably dropped. */
        } else if (s_repair_resume == BZ_RECOVERY_RECONCILE) {
            begin_reconcile();
        } else if (!finish_maintenance_locked(s_repair_resume)) {
            /* Another repair was scheduled, or a retryable read failed. */
        }
    } else {
        saturating_increment(&s_diagnostics.recovery_retry);
    }
}

void blind_zone_recovery_process(void)
{
    if (s_recovery == BZ_RECOVERY_IDLE || s_recovery == BZ_RECOVERY_READY) return;
    if (!ext_flash_try_lock_now(EXT_FLASH_OWNER_BLIND_ZONE)) return;

    if (s_recovery == BZ_RECOVERY_SCRATCH_CHECK) {
        recovery_scratch_check_locked();
    } else if (s_recovery == BZ_RECOVERY_SCRATCH_VALIDATE) {
        recovery_scratch_validate_locked();
    } else if (s_recovery == BZ_RECOVERY_SCRATCH_VICTIM_VALIDATE) {
        recovery_scratch_victim_validate_locked();
    } else if (s_recovery == BZ_RECOVERY_SCRATCH_DISCARD) {
        recovery_scratch_discard_locked();
    } else if (s_recovery == BZ_RECOVERY_META) {
        recovery_meta_locked();
    } else if (s_recovery == BZ_RECOVERY_DATA) {
        recovery_data_locked();
    } else if (s_recovery == BZ_RECOVERY_RECONCILE) {
        recovery_reconcile_locked();
    } else if (s_recovery == BZ_RECOVERY_FINALIZE) {
        recovery_finalize_locked();
    } else if (s_recovery == BZ_RECOVERY_CLEANUP) {
        recovery_cleanup_locked();
    } else if (s_recovery == BZ_RECOVERY_CONSUME) {
        recovery_consume_locked();
    } else if (s_recovery == BZ_RECOVERY_CONSUME_META) {
        recovery_consume_meta_locked();
    } else if (s_recovery == BZ_RECOVERY_ROLLOVER_SCAN) {
        recovery_rollover_scan_locked();
    } else if (s_recovery == BZ_RECOVERY_ROLLOVER_ERASE) {
        recovery_rollover_erase_locked();
    } else if (s_recovery == BZ_RECOVERY_REPAIR_BEGIN_ERASE) {
        recovery_repair_begin_erase_locked();
    } else if (s_recovery == BZ_RECOVERY_REPAIR_BACKUP) {
        recovery_repair_backup_locked();
    } else if (s_recovery == BZ_RECOVERY_REPAIR_HEADER) {
        recovery_repair_header_locked();
    } else if (s_recovery == BZ_RECOVERY_REPAIR_VALIDATE) {
        recovery_repair_validate_locked();
    } else if (s_recovery == BZ_RECOVERY_REPAIR_VICTIM_ERASE) {
        recovery_repair_victim_erase_locked();
    } else if (s_recovery == BZ_RECOVERY_REPAIR_RESTORE) {
        recovery_repair_restore_locked();
    } else if (s_recovery == BZ_RECOVERY_REPAIR_VERIFY) {
        recovery_repair_verify_locked();
    } else if (s_recovery == BZ_RECOVERY_REPAIR_FINAL_ERASE) {
        recovery_repair_final_erase_locked();
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
    if (record == NULL || record->event_id == 0U ||
        record->length > BLIND_ZONE_LOCATION_MAX)
        return BLIND_ZONE_INVALID;
    if (s_have_last_record && record->event_id == s_last_record.event_id) {
        if (!same_public_record(record, &s_last_record)) return BLIND_ZONE_INVALID;
        return blind_zone_ready() ? BLIND_ZONE_OK : BLIND_ZONE_PENDING;
    }
    if (s_append_state != BZ_APPEND_NONE) {
        if (!same_append_record(record)) {
            saturating_increment(&s_diagnostics.busy);
            return BLIND_ZONE_BUSY;
        }
        if (s_append_state == BZ_APPEND_COMMITTED && blind_zone_ready()) {
            s_append_state = BZ_APPEND_NONE;
            return BLIND_ZONE_OK;
        }
        if (s_append_state == BZ_APPEND_UNCERTAIN || !blind_zone_ready())
            return BLIND_ZONE_PENDING;
        s_append_state = BZ_APPEND_NONE;
    }
    if (!blind_zone_ready()) {
        saturating_increment(&s_diagnostics.busy);
        return BLIND_ZONE_BUSY;
    }
    if (!ext_flash_try_lock_now(EXT_FLASH_OWNER_BLIND_ZONE)) {
        saturating_increment(&s_diagnostics.busy);
        return BLIND_ZONE_BUSY;
    }

    /* A completed data write with torn metadata is adopted before accepting new input. */
    if (read_record_locked(s_next_slot, &existing) && flash_record_valid(&existing) &&
        existing.sequence == s_next_sequence) {
        if (adopt_record_locked(s_next_slot, s_span + 1U) != BZ_META_OK) {
            begin_reconcile();
            ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
            saturating_increment(&s_diagnostics.pending_reconciliation);
            return BLIND_ZONE_PENDING;
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
                saturating_increment(&s_diagnostics.append_io);
                ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
                return BLIND_ZONE_IO_ERROR;
            }
        }
        if (!read_record_locked(write_slot, &existing)) {
            saturating_increment(&s_diagnostics.append_io);
            ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
            return BLIND_ZONE_IO_ERROR;
        }
        if (slot_erased(&existing)) break;
        if (span >= BLIND_ZONE_PHYSICAL_SLOTS - 1U) {
            saturating_increment(&s_diagnostics.append_io);
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
    flash_record.event_id = record->event_id;
    flash_record.sequence = s_next_sequence;
    memcpy(flash_record.location, record->location, record->length);
    flash_record.crc32 = crc32_compute(&flash_record,
                                     (uint32_t)offsetof(bz_flash_record_t, crc32));
    flash_record.commit_marker = 0xffffffffUL;
    if (!ext_flash_write_verified(EXT_FLASH_OWNER_BLIND_ZONE, record_addr(write_slot),
                                  &flash_record,
                                  (uint32_t)offsetof(bz_flash_record_t, commit_marker))) {
        saturating_increment(&s_diagnostics.io_precommit_drop);
        mark_repair_slot(write_slot);
        start_repair_locked(write_slot / BZ_DATA_PER_SECTOR, BZ_RECOVERY_READY);
        ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
        return BLIND_ZONE_IO_ERROR;
    }
    {
        ext_flash_program_result_t marker_result = ext_flash_write_result(
            EXT_FLASH_OWNER_BLIND_ZONE,
            record_addr(write_slot) +
                offsetof(bz_flash_record_t, commit_marker),
            &commit, sizeof(commit));
        if (marker_result == EXT_FLASH_PROGRAM_NOT_ISSUED) {
            begin_append_transaction(record);
            begin_reconcile();
            saturating_increment(&s_diagnostics.pending_reconciliation);
            ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
            return BLIND_ZONE_PENDING;
        }
        if (marker_result == EXT_FLASH_PROGRAM_ISSUED_UNCERTAIN) {
            begin_append_transaction(record);
            begin_reconcile();
            saturating_increment(&s_diagnostics.pending_reconciliation);
            ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
            return BLIND_ZONE_PENDING;
        }
    }

    head = s_head_slot;
    count = s_count;
    ++span;
    if (count == BLIND_ZONE_LOGICAL_CAPACITY) {
        uint32_t skipped;
        uint32_t new_head = advance_to_sequence_locked(
            head, span, s_next_sequence - count + 1U, &skipped);
        if (new_head >= BLIND_ZONE_PHYSICAL_SLOTS) {
            begin_append_transaction(record);
            begin_reconcile();
            saturating_increment(&s_diagnostics.pending_reconciliation);
            ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
            return BLIND_ZONE_PENDING;
        }
        head = new_head;
        span -= skipped;
        saturating_increment(&s_diagnostics.oldest_overwrite);
    } else {
        ++count;
    }
    {
        bz_meta_result_t committed = commit_meta_locked(
            head, count, span, (write_slot + 1U) % BLIND_ZONE_PHYSICAL_SLOTS,
            s_next_sequence + 1U);
        if (committed != BZ_META_OK) {
            begin_append_transaction(record);
            if (committed == BZ_META_ERROR) begin_reconcile();
            saturating_increment(&s_diagnostics.pending_reconciliation);
            ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
            return BLIND_ZONE_PENDING;
        }
    }
    cache_public_record(record, s_next_sequence - 1U);
    ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
    return BLIND_ZONE_OK;
}

uint8_t blind_zone_peek(blind_zone_record_t *records, uint8_t capacity,
                        uint32_t *first_sequence)
{
    uint8_t copied = 0U;
    uint32_t slot;
    uint32_t scanned = 0U;
    uint32_t copied_after_slot = 0U;
    uint32_t copied_used_slots = 0U;
    uint32_t expected;
    bool read_failed = false;
    if (!blind_zone_ready() || records == NULL || first_sequence == NULL || capacity == 0U)
        return 0U;
    if (capacity > BZ_PEEK_SNAPSHOT_MAX) capacity = BZ_PEEK_SNAPSHOT_MAX;
    if (!ext_flash_try_lock_now(EXT_FLASH_OWNER_BLIND_ZONE)) {
        saturating_increment(&s_diagnostics.busy);
        return 0U;
    }
    slot = s_head_slot;
    expected = s_next_sequence - s_count;
    while (copied < capacity && copied < s_count && scanned < s_span) {
        bz_flash_record_t record;
        if (!read_record_locked(slot, &record)) {
            saturating_increment(&s_diagnostics.recovery_retry);
            read_failed = true;
            break;
        }
        ++scanned;
        slot = (slot + 1U) % BLIND_ZONE_PHYSICAL_SLOTS;
        if (!flash_record_valid(&record) || record.sequence != expected + copied)
            continue;
        records[copied].length = (uint8_t)record.length;
        records[copied].event_id = record.event_id;
        memcpy(records[copied].location, record.location, record.length);
        if (record.length < BLIND_ZONE_LOCATION_MAX)
            memset(records[copied].location + record.length, 0,
                   BLIND_ZONE_LOCATION_MAX - record.length);
        if (copied == 0U) *first_sequence = record.sequence;
        if (copied < BZ_PEEK_SNAPSHOT_MAX) s_peek_slots[copied] =
            (slot + BLIND_ZONE_PHYSICAL_SLOTS - 1U) % BLIND_ZONE_PHYSICAL_SLOTS;
        ++copied;
        copied_after_slot = slot;
        copied_used_slots = scanned;
    }
    if (copied != 0U && copied <= BZ_PEEK_SNAPSHOT_MAX) {
        s_peek_first_sequence = *first_sequence;
        s_peek_count = copied;
        s_peek_after_slot = copied_after_slot;
        s_peek_used_slots = copied_used_slots;
    }
    if (copied == 0U && s_count != 0U && !read_failed) {
        mark_repair_slot(s_head_slot);
        s_quarantine_pending = true;
        start_repair_locked(s_head_slot / BZ_DATA_PER_SECTOR,
                            BZ_RECOVERY_READY);
    } else if (copied != 0U && copied < capacity && copied < s_count && !read_failed &&
               scanned < s_span) {
        mark_repair_slot((slot + BLIND_ZONE_PHYSICAL_SLOTS - 1U) %
                         BLIND_ZONE_PHYSICAL_SLOTS);
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
    uint32_t old_head;
    uint32_t old_span;
    if (s_consume_complete && first_sequence == s_consume_first_sequence &&
        count == s_consume_count) {
        s_consume_complete = false;
        s_consume_count = 0U;
        return BLIND_ZONE_OK;
    }
    if (!blind_zone_ready()) {
        saturating_increment(&s_diagnostics.busy);
        return BLIND_ZONE_BUSY;
    }
    if (count == 0U || count > s_count) return BLIND_ZONE_INVALID;
    expected = s_next_sequence - s_count;
    if (first_sequence != expected) {
        if ((int32_t)(first_sequence - expected) < 0) {
            saturating_increment(&s_diagnostics.stale_ack_overwrite);
            return BLIND_ZONE_STALE;
        }
        return BLIND_ZONE_INVALID;
    }
    if (s_peek_count != count || s_peek_first_sequence != first_sequence)
        return BLIND_ZONE_INVALID;
    if (!ext_flash_try_lock_now(EXT_FLASH_OWNER_BLIND_ZONE)) {
        saturating_increment(&s_diagnostics.busy);
        return BLIND_ZONE_BUSY;
    }
    old_head = s_head_slot;
    old_span = s_span;
    remaining = s_count - count;
    if (remaining == 0U) {
        head = s_next_slot;
        span = 0U;
    } else {
        head = s_peek_after_slot;
        skipped = s_peek_used_slots;
        span = s_span - skipped;
    }
    s_consume_cursor = old_head;
    s_consume_slots = old_span - span;
    s_consume_first_sequence = first_sequence;
    s_consume_count = count;
    s_consume_head = head;
    s_consume_remaining = remaining;
    s_consume_span = span;
    s_consume_complete = false;
    memcpy(s_consume_targets, s_peek_slots,
           count * sizeof(s_consume_targets[0]));
    s_consume_target_count = count;
    s_consume_target_index = 0U;
    s_peek_count = 0U;
    s_recovery = BZ_RECOVERY_CONSUME;
    ext_flash_unlock(EXT_FLASH_OWNER_BLIND_ZONE);
    return BLIND_ZONE_PENDING;
}
