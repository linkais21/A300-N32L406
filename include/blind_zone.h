#ifndef BLIND_ZONE_H
#define BLIND_ZONE_H

#include <stdbool.h>
#include <stdint.h>

#define BLIND_ZONE_LOCATION_MAX       40U
#define BLIND_ZONE_LOGICAL_CAPACITY   9900UL
#define BLIND_ZONE_PHYSICAL_SLOTS     10176UL
#define BLIND_ZONE_PEEK_MAX           11U

typedef enum {
    BLIND_ZONE_OK = 0,
    BLIND_ZONE_PENDING,
    BLIND_ZONE_BUSY,
    BLIND_ZONE_STALE,
    BLIND_ZONE_INVALID,
    BLIND_ZONE_IO_ERROR,
} blind_zone_result_t;

typedef struct {
    uint32_t busy;
    uint32_t io_precommit_drop;
    uint32_t corrupt_quarantine;
    uint32_t oldest_overwrite;
    uint32_t pending_reconciliation;
    uint32_t append_io;
    uint32_t consume_io;
    uint32_t recovery_retry;
    uint32_t format_rejected;
    uint32_t stale_ack_overwrite;
} blind_zone_diagnostics_t;

typedef struct {
    uint32_t event_id;
    uint8_t length;
    uint8_t location[BLIND_ZONE_LOCATION_MAX];
} blind_zone_record_t;

bool blind_zone_init(void);
void blind_zone_recovery_process(void);
bool blind_zone_ready(void);
blind_zone_result_t blind_zone_append(const blind_zone_record_t *record);
uint8_t blind_zone_peek(blind_zone_record_t *records, uint8_t capacity,
                        uint32_t *first_sequence);
blind_zone_result_t blind_zone_consume(uint32_t first_sequence, uint8_t count);
void blind_zone_get_diagnostics(blind_zone_diagnostics_t *out);
#ifdef BLIND_ZONE_TEST
typedef enum {
    BLIND_ZONE_TEST_RECOVERY_OTHER = 0,
    BLIND_ZONE_TEST_RECOVERY_ROLLOVER_SCAN,
    BLIND_ZONE_TEST_RECOVERY_ROLLOVER_ERASE,
    BLIND_ZONE_TEST_RECOVERY_SCRATCH_BACKUP,
    BLIND_ZONE_TEST_RECOVERY_SCRATCH_HEADER,
    BLIND_ZONE_TEST_RECOVERY_VICTIM_ERASE,
    BLIND_ZONE_TEST_RECOVERY_VICTIM_RESTORE,
    BLIND_ZONE_TEST_RECOVERY_SCRATCH_ERASE,
} blind_zone_test_recovery_state_t;
void blind_zone_test_set_diagnostics(const blind_zone_diagnostics_t *value);
blind_zone_test_recovery_state_t blind_zone_test_recovery_state(void);
#endif

#endif
