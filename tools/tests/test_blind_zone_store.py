#!/usr/bin/env python3
"""Host NOR/power-cut tests for the external-Flash blind-zone FIFO."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def compiler() -> str:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    if not cc:
        located = subprocess.run(
            ["where.exe", "gcc.exe"], capture_output=True, text=True, check=False
        )
        if located.returncode == 0 and located.stdout.strip():
            cc = located.stdout.splitlines()[0].strip()
    if not cc:
        winlibs = list(
            (Path.home() / "AppData/Local/Microsoft/WinGet/Packages").glob(
                "BrechtSanders.WinLibs*/mingw64/bin/gcc.exe"
            )
        )
        if winlibs:
            cc = str(winlibs[0])
    if not cc:
        raise RuntimeError("a host C compiler is required")
    return cc


HARNESS = r'''
#include "blind_zone.h"
#include "ext_flash_store.h"
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define FLASH_BYTES (2U * 1024U * 1024U)
#define SECTOR_BYTES 4096U
#define BLIND_META_ADDR 0x110000UL
#define BLIND_DATA_ADDR 0x111000UL
#define BLIND_SCRATCH_ADDR 0x1b0000UL
#define RECORD_BYTES 64U
#define DATA_SLOTS_PER_SECTOR (SECTOR_BYTES / RECORD_BYTES)
#define META_BYTES 40U
#define META_COMMIT_OFFSET 36U
#define RECORD_EVENT_ID_OFFSET 8U
#define RECORD_SEQUENCE_OFFSET 12U
#define RECORD_LOCATION_OFFSET 16U
#define RECORD_CRC_OFFSET 56U

static uint8_t flash_mem[FLASH_BYTES];
static ext_flash_owner_t owner;
static int fail_after = -1;
static unsigned erase_count;
static uint32_t fail_read_address = 0xffffffffUL;
static bool fail_read_once;
static bool fail_marker_program_noop;
static bool delay_marker_program;
static bool delayed_marker_pending;
static uint32_t delayed_marker_address;
static uint32_t delayed_marker_value;

bool ext_flash_try_lock(ext_flash_owner_t requested)
{
    if (requested == EXT_FLASH_OWNER_NONE || owner != EXT_FLASH_OWNER_NONE) return false;
    owner = requested;
    return true;
}

bool ext_flash_try_lock_now(ext_flash_owner_t requested)
{
    return ext_flash_try_lock(requested);
}

void ext_flash_unlock(ext_flash_owner_t requested)
{
    if (owner == requested) owner = EXT_FLASH_OWNER_NONE;
}

bool ext_flash_read(ext_flash_owner_t requested, uint32_t address, void *data, uint32_t length)
{
    if (owner != requested || data == NULL || address > FLASH_BYTES || length > FLASH_BYTES - address)
        return false;
    if (fail_read_once && address == fail_read_address) {
        fail_read_once = false;
        return false;
    }
    if (delayed_marker_pending) {
        memcpy(flash_mem + delayed_marker_address, &delayed_marker_value,
               sizeof(delayed_marker_value));
        delayed_marker_pending = false;
    }
    memcpy(data, flash_mem + address, length);
    return true;
}

ext_flash_program_result_t ext_flash_write_result(
    ext_flash_owner_t requested, uint32_t address,
    const void *data, uint32_t length)
{
    if (owner != requested || data == NULL || address > FLASH_BYTES ||
        length > FLASH_BYTES - address)
        return EXT_FLASH_PROGRAM_NOT_ISSUED;
    if (fail_marker_program_noop && address >= BLIND_DATA_ADDR &&
        ((address - BLIND_DATA_ADDR) % RECORD_BYTES) == 60U) {
        fail_marker_program_noop = false;
        return EXT_FLASH_PROGRAM_NOT_ISSUED;
    }
    if (delay_marker_program && address >= BLIND_DATA_ADDR &&
        ((address - BLIND_DATA_ADDR) % RECORD_BYTES) == 60U &&
        length == sizeof(uint32_t)) {
        delay_marker_program = false;
        delayed_marker_pending = true;
        delayed_marker_address = address;
        memcpy(&delayed_marker_value, data, sizeof(delayed_marker_value));
        return EXT_FLASH_PROGRAM_ISSUED_UNCERTAIN;
    }
    if (!ext_flash_write_verified(requested, address, data, length))
        return EXT_FLASH_PROGRAM_ISSUED_UNCERTAIN;
    return EXT_FLASH_PROGRAM_VERIFIED;
}

bool ext_flash_write_verified(ext_flash_owner_t requested, uint32_t address,
                              const void *data, uint32_t length)
{
    const uint8_t *source = (const uint8_t *)data;
    uint32_t i;
    if (owner != requested || data == NULL || address > FLASH_BYTES || length > FLASH_BYTES - address)
        return false;
    if (fail_marker_program_noop && address >= BLIND_DATA_ADDR &&
        ((address - BLIND_DATA_ADDR) % RECORD_BYTES) == 60U) {
        fail_marker_program_noop = false;
        return false;
    }
    for (i = 0U; i < length; ++i) {
        if (fail_after == 0) return false;
        if ((flash_mem[address + i] & source[i]) != source[i]) return false;
        flash_mem[address + i] &= source[i];
        if (fail_after > 0) --fail_after;
    }
    return memcmp(flash_mem + address, data, length) == 0;
}

bool ext_flash_erase(ext_flash_owner_t requested, uint32_t address, uint32_t length)
{
    uint32_t i;
    if (owner != requested || address % SECTOR_BYTES != 0U || length % SECTOR_BYTES != 0U ||
        address > FLASH_BYTES || length > FLASH_BYTES - address)
        return false;
    for (i = 0U; i < length; ++i) {
        if (fail_after == 0) return false;
        flash_mem[address + i] = 0xffU;
        if (fail_after > 0) --fail_after;
    }
    erase_count += length / SECTOR_BYTES;
    return true;
}

static blind_zone_record_t make_record(uint32_t value)
{
    blind_zone_record_t record;
    unsigned i;
    memset(&record, 0, sizeof(record));
    record.event_id = value;
    record.length = BLIND_ZONE_LOCATION_MAX;
    for (i = 0U; i < record.length; ++i)
        record.location[i] = (uint8_t)(value + i * 17U);
    record.location[0] = (uint8_t)(value >> 24);
    record.location[1] = (uint8_t)(value >> 16);
    record.location[2] = (uint8_t)(value >> 8);
    record.location[3] = (uint8_t)value;
    return record;
}

static uint32_t record_value(const blind_zone_record_t *record)
{
    return ((uint32_t)record->location[0] << 24) |
           ((uint32_t)record->location[1] << 16) |
           ((uint32_t)record->location[2] << 8) |
           record->location[3];
}

static uint32_t test_crc32(const uint8_t *bytes, uint32_t length)
{
    uint32_t crc = 0xffffffffUL, i;
    uint8_t bit;
    for (i = 0U; i < length; ++i) {
        crc ^= bytes[i];
        for (bit = 0U; bit < 8U; ++bit)
            crc = (crc >> 1) ^ ((crc & 1U) ? 0xedb88320UL : 0U);
    }
    return crc ^ 0xffffffffUL;
}

static void forge_record_from_slot0(uint32_t slot, uint32_t sequence, uint32_t value)
{
    uint8_t *record = flash_mem + BLIND_DATA_ADDR + slot * RECORD_BYTES;
    uint32_t crc;
    memcpy(record, flash_mem + BLIND_DATA_ADDR, RECORD_BYTES);
    memcpy(record + RECORD_SEQUENCE_OFFSET, &sequence, sizeof(sequence));
    record[RECORD_LOCATION_OFFSET] = (uint8_t)(value >> 24);
    record[RECORD_LOCATION_OFFSET + 1U] = (uint8_t)(value >> 16);
    record[RECORD_LOCATION_OFFSET + 2U] = (uint8_t)(value >> 8);
    record[RECORD_LOCATION_OFFSET + 3U] = (uint8_t)value;
    crc = test_crc32(record, 56U);
    memcpy(record + RECORD_CRC_OFFSET, &crc, sizeof(crc));
}

static void recover(void)
{
    unsigned calls = 0U;
    assert(blind_zone_init());
    while (!blind_zone_ready() && calls++ < 3000U) blind_zone_recovery_process();
    assert(blind_zone_ready());
    assert(calls < 3000U);
}

static void append_accepted(const blind_zone_record_t *record)
{
    unsigned calls = 0U;
    blind_zone_result_t result = blind_zone_append(record);
    assert(result == BLIND_ZONE_OK || result == BLIND_ZONE_PENDING);
    while (!blind_zone_ready() && calls++ < 3000U) blind_zone_recovery_process();
    assert(blind_zone_ready() && calls < 3000U);
    if (result == BLIND_ZONE_PENDING)
        assert(blind_zone_append(record) == BLIND_ZONE_OK);
}

static void maintenance_ready(void)
{
    unsigned calls = 0U;
    while (!blind_zone_ready() && calls++ < 3000U) blind_zone_recovery_process();
    assert(blind_zone_ready() && calls < 3000U);
}

static void consume_accepted(uint32_t sequence, uint8_t count)
{
    blind_zone_record_t snapshot[12];
    uint32_t first = 0U;
    assert(count <= 12U);
    assert(blind_zone_peek(snapshot, count, &first) == count);
    assert(first == sequence);
    blind_zone_result_t result = blind_zone_consume(sequence, count);
    assert(result == BLIND_ZONE_OK || result == BLIND_ZONE_PENDING);
    maintenance_ready();
}

static void expect_front(uint32_t value, uint32_t expected_sequence)
{
    blind_zone_record_t record;
    uint32_t sequence = 0U;
    assert(blind_zone_peek(&record, 1U, &sequence) == 1U);
    if (sequence != expected_sequence)
        fprintf(stderr, "expect_front value=%lu expected_seq=%lu got_seq=%lu got_value=%lu\n",
                (unsigned long)value, (unsigned long)expected_sequence,
                (unsigned long)sequence, (unsigned long)record_value(&record));
    assert(sequence == expected_sequence);
    assert(record.length == BLIND_ZONE_LOCATION_MAX);
    assert(record_value(&record) == value);
}

static void test_exact_capacity_and_event_identity_contract(void)
{
    blind_zone_record_t first = make_record(41U);
    blind_zone_record_t same_payload = first;
    blind_zone_record_t conflicting = first;
    blind_zone_record_t invalid = first;
    blind_zone_record_t out[2];
    uint32_t sequence = 0U;

    assert(BLIND_ZONE_LOGICAL_CAPACITY == 9900UL);
    assert(BLIND_ZONE_PHYSICAL_SLOTS == 10176UL);
    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE;
    fail_after = -1;
    recover();

    invalid.event_id = 0U;
    assert(blind_zone_append(&invalid) == BLIND_ZONE_INVALID);

    append_accepted(&first);
    conflicting.location[0] ^= 0x5aU;
    assert(blind_zone_append(&conflicting) == BLIND_ZONE_INVALID);

    same_payload.event_id = 42U;
    append_accepted(&same_payload);
    assert(blind_zone_peek(out, 2U, &sequence) == 2U);
    assert(sequence == 1U);
    assert(out[0].event_id == 41U && out[1].event_id == 42U);
    assert(memcmp(out[0].location, out[1].location,
                  BLIND_ZONE_LOCATION_MAX) == 0);
}

static void test_fifo_reboot_capacity_and_sector_reclaim(void)
{
    uint32_t i;
    blind_zone_record_t batch[7];
    uint32_t sequence;
    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE;
    recover();

    for (i = 1U; i <= 3U; ++i) {
        blind_zone_record_t record = make_record(i);
        append_accepted(&record);
    }
    recover();
    assert(blind_zone_peek(batch, 7U, &sequence) == 3U && sequence == 1U);
    for (i = 0U; i < 3U; ++i) assert(record_value(&batch[i]) == i + 1U);
    consume_accepted(sequence, 2U);
    expect_front(3U, 3U);

    /* Refill from one live item to the exact logical capacity. */
    for (i = 4U; i <= BLIND_ZONE_LOGICAL_CAPACITY + 2U; ++i) {
        blind_zone_record_t record = make_record(i);
        append_accepted(&record);
    }
    expect_front(3U, 3U);
    {
        blind_zone_record_t record = make_record(BLIND_ZONE_LOGICAL_CAPACITY + 3U);
        append_accepted(&record);
    }
    expect_front(4U, 4U); /* full append overwrites exactly one oldest record */

    /* Cross the physical wrap and force sector-safe reclamation. */
    for (i = BLIND_ZONE_LOGICAL_CAPACITY + 4U;
         i <= BLIND_ZONE_LOGICAL_CAPACITY + 260U; ++i) {
        blind_zone_record_t record = make_record(i);
        append_accepted(&record);
    }
    recover();
    expect_front(261U, 261U);
    assert(erase_count > 1U); /* metadata rotations plus reclaimed data sectors */

    /* A lost journal rebuilds the retained logical FIFO. */
    memset(flash_mem + BLIND_META_ADDR, 0xff, SECTOR_BYTES);
    recover();
    expect_front(261U, 261U);
}

static void test_crc_metadata_selection_and_torn_metadata_scan(void)
{
    blind_zone_record_t r;
    uint32_t seq;
    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE;
    recover();
    r = make_record(11U); append_accepted(&r);
    r = make_record(12U); append_accepted(&r);

    /* Latest metadata entry is torn: recovery must select the previous valid generation. */
    flash_mem[BLIND_META_ADDR + 2U * META_BYTES + META_COMMIT_OFFSET] = 0x00U;
    recover();
    assert(blind_zone_peek(&r, 1U, &seq) == 1U && seq == 1U && record_value(&r) == 11U);

    /* No valid journal after an interrupted metadata-sector rewrite: bounded data scan wins. */
    memset(flash_mem + BLIND_META_ADDR, 0xff, SECTOR_BYTES);
    recover();
    assert(blind_zone_peek(&r, 1U, &seq) == 1U && seq == 1U && record_value(&r) == 11U);
    consume_accepted(seq, 1U);
    expect_front(12U, 2U);

    /* CRC-corrupt only remaining record is never exposed as a location. */
    flash_mem[BLIND_DATA_ADDR + RECORD_BYTES] &= 0x2fU;
    recover();
    assert(blind_zone_peek(&r, 1U, &seq) == 0U);
}

static void test_journalled_boot_repairs_damaged_sector_before_ready(void)
{
    blind_zone_record_t record;
    uint32_t sequence = 0U;

    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    record = make_record(91U); append_accepted(&record);
    record = make_record(92U); append_accepted(&record);

    /* The journal remains valid: boot must still inspect and repair the
     * damaged sector before exposing the surviving suffix. */
    flash_mem[BLIND_DATA_ADDR] &= 0x2fU;
    owner = EXT_FLASH_OWNER_NONE;
    recover();
    assert(blind_zone_peek(&record, 1U, &sequence) == 1U);
    assert(sequence == 2U && record_value(&record) == 92U);
}

static void assert_scratch_erased(void)
{
    unsigned i;
    for (i = 0U; i < SECTOR_BYTES; ++i)
        assert(flash_mem[BLIND_SCRATCH_ADDR + i] == 0xffU);
}

static void test_prepared_record_is_finalized_after_reset(void)
{
    blind_zone_record_t record = make_record(93U), out;
    uint32_t sequence = 0U;

    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    fail_marker_program_noop = true;
    assert(blind_zone_append(&record) == BLIND_ZONE_PENDING);
    assert(blind_zone_append(&record) == BLIND_ZONE_PENDING);
    owner = EXT_FLASH_OWNER_NONE;
    recover();
    assert(blind_zone_append(&record) == BLIND_ZONE_OK);
    assert(blind_zone_peek(&out, 1U, &sequence) == 1U);
    assert(sequence == 1U && out.event_id == record.event_id &&
           record_value(&out) == 93U);
}

static void test_runtime_prepared_finalizes_in_original_nonboundary_slot(void)
{
    blind_zone_record_t seed = make_record(94U), record = make_record(95U), out;
    uint32_t sequence = 0U;
    uint8_t *slot;

    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    append_accepted(&seed);
    consume_accepted(1U, 1U); /* next slot 1: not a sector boundary */
    fail_marker_program_noop = true;
    assert(blind_zone_append(&record) == BLIND_ZONE_PENDING);
    maintenance_ready();
    slot = flash_mem + BLIND_DATA_ADDR + RECORD_BYTES;
    assert(*(uint32_t *)(void *)(slot + 60U) == 0x434d4954UL);
    assert(blind_zone_append(&record) == BLIND_ZONE_OK);
    assert(blind_zone_peek(&out, 1U, &sequence) == 1U && sequence == 2U);
    assert(out.event_id == record.event_id && record_value(&out) == 95U);
}

static void test_scratch_phase_cut_restores_exact_slots(void)
{
    static const blind_zone_test_recovery_state_t phases[] = {
        BLIND_ZONE_TEST_RECOVERY_SCRATCH_BACKUP,
        BLIND_ZONE_TEST_RECOVERY_SCRATCH_HEADER,
        BLIND_ZONE_TEST_RECOVERY_VICTIM_ERASE,
        BLIND_ZONE_TEST_RECOVERY_VICTIM_RESTORE,
        BLIND_ZONE_TEST_RECOVERY_SCRATCH_ERASE,
    };
    unsigned phase;

    for (phase = 0U; phase < sizeof(phases) / sizeof(phases[0]); ++phase) {
        blind_zone_record_t record;
        uint8_t first[RECORD_BYTES], third[RECORD_BYTES];
        unsigned calls = 0U;

        memset(flash_mem, 0xff, sizeof(flash_mem));
        owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
        record = make_record(101U); append_accepted(&record);
        record = make_record(102U); append_accepted(&record);
        record = make_record(103U); append_accepted(&record);
        memcpy(first, flash_mem + BLIND_DATA_ADDR, sizeof(first));
        memcpy(third, flash_mem + BLIND_DATA_ADDR + 2U * RECORD_BYTES,
               sizeof(third));
        flash_mem[BLIND_DATA_ADDR + RECORD_BYTES] &= 0x2fU;

        assert(blind_zone_init());
        while (blind_zone_test_recovery_state() != phases[phase] &&
               calls++ < 3000U)
            blind_zone_recovery_process();
        assert(calls < 3000U);
        fail_after = 0;
        blind_zone_recovery_process();
        fail_after = -1;
        owner = EXT_FLASH_OWNER_NONE;
        recover();
        assert(memcmp(flash_mem + BLIND_DATA_ADDR, first, sizeof(first)) == 0);
        assert(memcmp(flash_mem + BLIND_DATA_ADDR + 2U * RECORD_BYTES,
                      third, sizeof(third)) == 0);
        assert_scratch_erased();
    }
}

static void test_repeated_sector_repairs_make_forward_progress(void)
{
    blind_zone_record_t record;
    uint32_t sequence = 0U;
    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    record = make_record(111U); append_accepted(&record);
    record = make_record(112U); append_accepted(&record);
    record = make_record(113U); append_accepted(&record);
    flash_mem[BLIND_DATA_ADDR + RECORD_BYTES] &= 0x2fU;
    owner = EXT_FLASH_OWNER_NONE; recover();
    flash_mem[BLIND_DATA_ADDR + 2U * RECORD_BYTES] &= 0x2fU;
    owner = EXT_FLASH_OWNER_NONE; recover();
    record = make_record(114U); append_accepted(&record);
    assert(blind_zone_peek(&record, 1U, &sequence) <= 1U);
    assert_scratch_erased();
}

static void test_full_capacity_prepared_and_distributed_repairs_progress(void)
{
    blind_zone_record_t record;
    uint32_t i;

    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    for (i = 1U; i <= BLIND_ZONE_LOGICAL_CAPACITY; ++i) {
        record = make_record(1000U + i);
        append_accepted(&record);
    }
    /* Damage four of the 276 physical spare slots in distinct sectors.  The
     * full FIFO must still admit a PREPARED event and repair around them. */
    for (i = 0U; i < 4U; ++i) {
        flash_mem[BLIND_DATA_ADDR +
                  (BLIND_ZONE_LOGICAL_CAPACITY + i * DATA_SLOTS_PER_SECTOR) *
                  RECORD_BYTES] &=
            0x2fU;
    }
    record = make_record(12000U);
    delay_marker_program = true;
    assert(blind_zone_append(&record) == BLIND_ZONE_PENDING);
    owner = EXT_FLASH_OWNER_NONE;
    recover();
    assert(blind_zone_append(&record) == BLIND_ZONE_OK);
    record = make_record(12001U);
    append_accepted(&record);
    assert(blind_zone_ready());
    assert_scratch_erased();
}

static void test_remote_spare_sector_repair_preserves_full_fifo(void)
{
    blind_zone_record_t record, out[BLIND_ZONE_PEEK_MAX];
    uint32_t sequence = 0U, expected = 1U, i;

    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    for (i = 1U; i <= BLIND_ZONE_LOGICAL_CAPACITY; ++i) {
        record = make_record(i);
        append_accepted(&record);
    }
    /* Slot 9,900 is spare and lies far from the FIFO head.  Repairing its
     * sector must not shrink head/count/span to that sector. */
    flash_mem[BLIND_DATA_ADDR + BLIND_ZONE_LOGICAL_CAPACITY * RECORD_BYTES] &=
        0x2fU;
    owner = EXT_FLASH_OWNER_NONE;
    recover();
    while (expected <= BLIND_ZONE_LOGICAL_CAPACITY) {
        uint8_t want = (uint8_t)((BLIND_ZONE_LOGICAL_CAPACITY - expected + 1U) >
                                 BLIND_ZONE_PEEK_MAX ? BLIND_ZONE_PEEK_MAX :
                                 (BLIND_ZONE_LOGICAL_CAPACITY - expected + 1U));
        uint8_t got = blind_zone_peek(out, want, &sequence);
        uint8_t j;
        assert(got == want && sequence == expected);
        for (j = 0U; j < got; ++j)
            assert(record_value(&out[j]) == expected + j);
        consume_accepted(sequence, got);
        expected += got;
    }
    assert(blind_zone_peek(&record, 1U, &sequence) == 0U);
    assert_scratch_erased();
}

static void test_committed_scratch_reboot_preserves_middle_gap_prefix(void)
{
    blind_zone_record_t record, out[BLIND_ZONE_PEEK_MAX];
    uint32_t sequence = 0U, i;
    unsigned calls = 0U;

    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    for (i = 1U; i <= BLIND_ZONE_LOGICAL_CAPACITY; ++i) {
        record = make_record(i);
        append_accepted(&record);
    }
    flash_mem[BLIND_DATA_ADDR + 5000U * RECORD_BYTES] &= 0x2fU;
    assert(blind_zone_init());
    while (blind_zone_test_recovery_state() !=
           BLIND_ZONE_TEST_RECOVERY_VICTIM_ERASE && calls++ < 4000U)
        blind_zone_recovery_process();
    assert(calls < 4000U);
    owner = EXT_FLASH_OWNER_NONE;
    recover();
    assert(blind_zone_peek(out, BLIND_ZONE_PEEK_MAX, &sequence) ==
           BLIND_ZONE_PEEK_MAX);
    assert(sequence == 1U && record_value(&out[0]) == 1U &&
           record_value(&out[BLIND_ZONE_PEEK_MAX - 1U]) ==
               BLIND_ZONE_PEEK_MAX);
}

static void test_capacity_limited_peek_does_not_queue_valid_sector_repair(void)
{
    blind_zone_record_t record, out[1];
    uint32_t sequence = 0U;
    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    record = make_record(20101U); append_accepted(&record);
    record = make_record(20102U); append_accepted(&record);
    assert(blind_zone_peek(out, 1U, &sequence) == 1U && sequence == 1U);
    assert(blind_zone_test_recovery_state() == BLIND_ZONE_TEST_RECOVERY_OTHER);
    assert(blind_zone_ready());
}

static void test_contention_and_power_cut_prefixes(void)
{
    uint8_t snapshot[SECTOR_BYTES + RECORD_BYTES];
    blind_zone_record_t r = make_record(77U);
    unsigned cut;
    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE;
    recover();
    memcpy(snapshot, flash_mem + BLIND_META_ADDR, sizeof(snapshot));
    assert(ext_flash_try_lock(EXT_FLASH_OWNER_OTA));
    assert(blind_zone_append(&r) == BLIND_ZONE_BUSY);
    assert(memcmp(snapshot, flash_mem + BLIND_META_ADDR, sizeof(snapshot)) == 0);
    ext_flash_unlock(EXT_FLASH_OWNER_OTA);
    assert(ext_flash_try_lock(EXT_FLASH_OWNER_CONFIG));
    assert(blind_zone_append(&r) == BLIND_ZONE_BUSY);
    assert(memcmp(snapshot, flash_mem + BLIND_META_ADDR, sizeof(snapshot)) == 0);
    ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);

    /* Inject cuts throughout record and metadata writes. Reboot exposes zero or one valid item. */
    for (cut = 0U; cut < 104U; cut += 7U) {
        blind_zone_record_t out;
        uint32_t seq = 0U;
        uint8_t count;
        memset(flash_mem, 0xff, sizeof(flash_mem));
        owner = EXT_FLASH_OWNER_NONE;
        fail_after = -1;
        recover();
        fail_after = (int)cut;
        (void)blind_zone_append(&r);
        fail_after = -1;
        owner = EXT_FLASH_OWNER_NONE;
        recover();
        count = blind_zone_peek(&out, 1U, &seq);
        assert(count <= 1U);
        if (count == 1U) assert(seq == 1U && record_value(&out) == 77U);
        {
            blind_zone_record_t replacement = make_record(88U);
            append_accepted(&replacement);
            if (count == 1U) {
                consume_accepted(1U, 1U);
                expect_front(88U, 2U);
            } else {
                expect_front(88U, 1U);
            }
        }
    }

    /* A torn mid-sector slot is skipped; NOR 0->1 rewriting is never attempted. */
    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE;
    fail_after = -1;
    recover();
    {
        blind_zone_record_t first = make_record(101U);
        blind_zone_record_t torn = make_record(102U);
        blind_zone_record_t replacement = make_record(103U);
        blind_zone_record_t out[2];
        uint32_t sequence;
        append_accepted(&first);
        fail_after = 20;
        assert(blind_zone_append(&torn) == BLIND_ZONE_IO_ERROR);
        fail_after = -1;
        owner = EXT_FLASH_OWNER_NONE;
        recover();
        append_accepted(&replacement);
        assert(blind_zone_peek(out, 2U, &sequence) == 2U && sequence == 1U);
        assert(record_value(&out[0]) == 101U && record_value(&out[1]) == 103U);
    }
}

static void test_two_cut_hole_then_committed_record_recovery(void)
{
    blind_zone_record_t seed = make_record(201U);
    blind_zone_record_t torn = make_record(202U);
    blind_zone_record_t committed = make_record(203U);
    blind_zone_record_t next = make_record(204U);
    blind_zone_record_t out[3];
    uint32_t sequence = 0U;

    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE;
    fail_after = -1;
    recover();

    /* Move next_slot inside a sector so the torn slot cannot be reclaimed by
     * the normal sector-boundary erase path. */
    append_accepted(&seed);
    consume_accepted(1U, 1U);

    /* First cut: leave invalid physical slot N while metadata still names N/S. */
    fail_after = 20;
    assert(blind_zone_append(&torn) == BLIND_ZONE_IO_ERROR);
    fail_after = -1;
    owner = EXT_FLASH_OWNER_NONE;
    recover();

    /* Second cut: skip N, fully commit S at N+1, then fail before the first
     * metadata byte. Runtime must stop accepting appends until reconciliation. */
    fail_after = RECORD_BYTES + 20;
    assert(blind_zone_append(&committed) == BLIND_ZONE_PENDING);
    fail_after = -1;
    assert(blind_zone_append(&next) == BLIND_ZONE_BUSY);

    /* Reboot recovery must scan past N, adopt N+1 as S, then allocate S+1. */
    owner = EXT_FLASH_OWNER_NONE;
    recover();
    append_accepted(&next);
    assert(blind_zone_peek(out, 3U, &sequence) == 2U);
    assert(sequence == 2U);
    assert(record_value(&out[0]) == 203U);
    assert(record_value(&out[1]) == 204U);
}

static void test_diagnostics_contract(void)
{
    blind_zone_diagnostics_t diagnostics;
    blind_zone_get_diagnostics(&diagnostics);
    assert(diagnostics.pending_reconciliation > 0U);
}

static void test_corrupt_head_and_middle_are_quarantined(void)
{
    blind_zone_record_t records[3];
    uint32_t sequence = 0U;
    blind_zone_diagnostics_t before, after;
    unsigned i;

    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    for (i = 1U; i <= 3U; ++i) { records[0] = make_record(300U + i); append_accepted(&records[0]); }
    blind_zone_get_diagnostics(&before);
    flash_mem[BLIND_DATA_ADDR] &= 0x2fU;
    assert(blind_zone_peek(records, 3U, &sequence) == 0U);
    maintenance_ready();
    assert(blind_zone_peek(records, 3U, &sequence) == 2U && sequence == 2U);
    assert(record_value(&records[0]) == 302U && record_value(&records[1]) == 303U);
    blind_zone_get_diagnostics(&after);
    assert(after.corrupt_quarantine == before.corrupt_quarantine + 1U);

    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    for (i = 1U; i <= 3U; ++i) { records[0] = make_record(400U + i); append_accepted(&records[0]); }
    flash_mem[BLIND_DATA_ADDR + RECORD_BYTES] &= 0x2fU;
    assert(blind_zone_peek(records, 3U, &sequence) == 1U && sequence == 1U);
    assert(record_value(&records[0]) == 401U);
    consume_accepted(1U, 1U);
    assert(blind_zone_peek(records, 2U, &sequence) == 0U);
    maintenance_ready();
    assert(blind_zone_peek(records, 2U, &sequence) == 1U && sequence == 3U);
    assert(record_value(&records[0]) == 403U);
}

static void test_structural_middle_corruption_does_not_stall_suffix(void)
{
    blind_zone_record_t record, out;
    uint32_t sequence = 0U;
    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    record = make_record(701U); append_accepted(&record);
    record = make_record(702U); append_accepted(&record);
    record = make_record(703U); append_accepted(&record);
    flash_mem[BLIND_DATA_ADDR + RECORD_BYTES] &= 0x2fU; /* corrupt magic */
    assert(blind_zone_peek(&out, 1U, &sequence) == 1U && sequence == 1U);
    consume_accepted(1U, 1U);
    assert(blind_zone_peek(&out, 1U, &sequence) == 0U);
    maintenance_ready();
    assert(blind_zone_peek(&out, 1U, &sequence) == 1U && sequence == 3U);
    assert(record_value(&out) == 703U);
}

static void test_transient_head_read_failure_never_quarantines_valid_head(void)
{
    blind_zone_record_t record;
    uint32_t sequence = 0U;
    blind_zone_diagnostics_t before, after;
    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    record = make_record(711U); append_accepted(&record);
    blind_zone_get_diagnostics(&before);
    fail_read_address = BLIND_DATA_ADDR;
    fail_read_once = true;
    assert(blind_zone_peek(&record, 1U, &sequence) == 0U);
    blind_zone_get_diagnostics(&after);
    assert(after.corrupt_quarantine == before.corrupt_quarantine);
    expect_front(711U, 1U);
}

static void test_consume_tombstones_precede_metadata_and_survive_each_cut(void)
{
    unsigned cut;
    for (cut = 1U; cut <= 3U; ++cut) {
        blind_zone_record_t record, out[BLIND_ZONE_PEEK_MAX];
        uint32_t sequence = 0U;
        unsigned i;
        memset(flash_mem, 0xff, sizeof(flash_mem));
        owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
        for (i = 1U; i <= 4U; ++i) {
            record = make_record(720U + i); append_accepted(&record);
        }
        assert(blind_zone_peek(out, 3U, &sequence) == 3U && sequence == 1U);
        assert(blind_zone_consume(1U, 3U) == BLIND_ZONE_PENDING);
        fail_after = (int)(cut * sizeof(uint32_t));
        blind_zone_recovery_process();
        fail_after = -1;
        owner = EXT_FLASH_OWNER_NONE;
        recover();
        assert(blind_zone_peek(out, 4U, &sequence) <= (uint8_t)(4U - cut));
        if (blind_zone_peek(out, 4U, &sequence) != 0U)
            assert(sequence > cut);
    }
}

static void test_issued_marker_timeout_later_commit_is_accepted_once(void)
{
    blind_zone_record_t record, out[2];
    uint32_t sequence = 0U;
    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    record = make_record(731U);
    delay_marker_program = true;
    assert(blind_zone_append(&record) == BLIND_ZONE_PENDING);
    assert(blind_zone_append(&record) == BLIND_ZONE_PENDING);
    maintenance_ready();
    assert(blind_zone_append(&record) == BLIND_ZONE_OK);
    assert(blind_zone_peek(out, 2U, &sequence) == 1U && sequence == 1U);
    assert(record_value(&out[0]) == 731U);
}

static void test_never_issued_marker_remains_pending_without_loss(void)
{
    blind_zone_record_t record, out[2];
    uint32_t sequence = 0U;
    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    record = make_record(732U);
    fail_marker_program_noop = true;
    assert(blind_zone_append(&record) == BLIND_ZONE_PENDING);
    maintenance_ready();
    assert(blind_zone_append(&record) == BLIND_ZONE_OK);
    assert(blind_zone_peek(out, 2U, &sequence) == 1U && sequence == 1U);
    assert(record_value(&out[0]) == 732U);
}

static void test_production_batch_sequence_corrupt_middle_survives_reboot(void)
{
    blind_zone_record_t record, out[11];
    uint32_t sequence = 0U, corrupt = 0x90000000UL;
    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    record = make_record(741U); append_accepted(&record);
    record = make_record(742U); append_accepted(&record);
    record = make_record(743U); append_accepted(&record);
    memcpy(flash_mem + BLIND_DATA_ADDR + RECORD_BYTES + RECORD_SEQUENCE_OFFSET,
           &corrupt, sizeof(corrupt));
    assert(blind_zone_peek(out, 11U, &sequence) == 1U && sequence == 1U);
    assert(blind_zone_consume(1U, 1U) == BLIND_ZONE_PENDING);
    maintenance_ready();
    owner = EXT_FLASH_OWNER_NONE;
    recover();
    assert(blind_zone_peek(out, 11U, &sequence) == 1U && sequence == 3U);
    assert(record_value(&out[0]) == 743U);
}

static void test_public_peek_capacity_is_clamped_to_production_max(void)
{
    struct {
        blind_zone_record_t records[BLIND_ZONE_PEEK_MAX];
        uint32_t guard;
    } output;
    blind_zone_record_t record;
    uint32_t sequence = 0U, i;
    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    for (i = 1U; i <= BLIND_ZONE_PEEK_MAX + 1U; ++i) {
        record = make_record(750U + i);
        append_accepted(&record);
    }
    output.guard = 0x51a7c0deUL;
    assert(blind_zone_peek(output.records, 0xffU, &sequence) ==
           BLIND_ZONE_PEEK_MAX);
    assert(sequence == 1U && output.guard == 0x51a7c0deUL);
}

static void test_full_ring_append_after_peek_makes_ack_stale(void)
{
    blind_zone_record_t record, out;
    uint32_t sequence = 0U, i;
    blind_zone_diagnostics_t before, after;
    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    for (i = 1U; i <= BLIND_ZONE_LOGICAL_CAPACITY; ++i) {
        record = make_record(i); append_accepted(&record);
    }
    assert(blind_zone_peek(&out, 1U, &sequence) == 1U && sequence == 1U);
    record = make_record(10001U); append_accepted(&record);
    blind_zone_get_diagnostics(&before);
    assert(blind_zone_consume(sequence, 1U) == BLIND_ZONE_STALE);
    blind_zone_get_diagnostics(&after);
    assert(after.stale_ack_overwrite == before.stale_ack_overwrite + 1U);
    expect_front(2U, 2U);
}

static void test_v1_media_fails_closed_and_counts_diagnostic(void)
{
    blind_zone_diagnostics_t before, after;
    unsigned calls = 0U;
    uint32_t magic = 0x425a4d31UL, commit = 0x434d4954UL;
    uint16_t version = 1U;
    memset(flash_mem, 0xff, sizeof(flash_mem));
    memcpy(flash_mem + BLIND_META_ADDR, &magic, sizeof(magic));
    memcpy(flash_mem + BLIND_META_ADDR + 4U, &version, sizeof(version));
    memcpy(flash_mem + BLIND_META_ADDR + META_COMMIT_OFFSET, &commit, sizeof(commit));
    blind_zone_get_diagnostics(&before);
    assert(blind_zone_init());
    while (calls++ < 100U) blind_zone_recovery_process();
    assert(!blind_zone_ready());
    blind_zone_get_diagnostics(&after);
    assert(after.format_rejected == before.format_rejected + 1U);
}

static void test_diagnostic_counters_saturate(void)
{
    blind_zone_diagnostics_t value, after;
    blind_zone_record_t record = make_record(999U);
    memset(&value, 0xff, sizeof(value));
    blind_zone_test_set_diagnostics(&value);
    owner = EXT_FLASH_OWNER_CONFIG;
    assert(blind_zone_append(&record) == BLIND_ZONE_BUSY);
    blind_zone_get_diagnostics(&after);
    assert(after.busy == 0xffffffffUL);
    owner = EXT_FLASH_OWNER_NONE;
}

static void test_full_metadata_journal_rollover_power_cuts(void)
{
    unsigned phase;
    for (phase = 0U; phase < 3U; ++phase) {
        blind_zone_record_t record, out[BLIND_ZONE_PEEK_MAX];
        uint32_t sequence = 0U;
        unsigned i;
        memset(flash_mem, 0xff, sizeof(flash_mem));
        owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
        for (i = 1U; i <= 101U; ++i) {
            record = make_record(800U + i); append_accepted(&record);
        }
        assert(blind_zone_peek(out, 1U, &sequence) == 1U && sequence == 1U);
        assert(blind_zone_consume(1U, 1U) == BLIND_ZONE_PENDING);
        while (blind_zone_test_recovery_state() !=
               BLIND_ZONE_TEST_RECOVERY_ROLLOVER_SCAN)
            blind_zone_recovery_process();
        if (phase == 0U) {
            fail_read_address = BLIND_DATA_ADDR;
            fail_read_once = true;
        } else {
            while (blind_zone_test_recovery_state() !=
                   BLIND_ZONE_TEST_RECOVERY_ROLLOVER_ERASE)
                blind_zone_recovery_process();
            fail_after = phase == 1U ? 0 : (int)(SECTOR_BYTES + 8U);
        }
        blind_zone_recovery_process();
        fail_after = -1; fail_read_once = false;
        owner = EXT_FLASH_OWNER_NONE;
        recover();
        if (blind_zone_peek(out, 1U, &sequence) == 0U) {
            maintenance_ready();
            owner = EXT_FLASH_OWNER_NONE;
            recover();
        }
        assert(blind_zone_peek(out, 1U, &sequence) == 1U);
        assert(sequence >= 2U);
        for (i = 2U; i <= 101U;) {
            uint8_t want = (uint8_t)((102U - i) > BLIND_ZONE_PEEK_MAX ?
                                     BLIND_ZONE_PEEK_MAX : (102U - i));
            uint8_t j;
            assert(blind_zone_peek(out, want, &sequence) == want);
            assert(sequence == i);
            for (j = 0U; j < want; ++j)
                assert(record_value(&out[j]) == 800U + i + j);
            assert(blind_zone_consume(sequence, want) == BLIND_ZONE_PENDING);
            maintenance_ready();
            i += want;
        }
        assert(blind_zone_peek(out, 1U, &sequence) == 0U);
    }
}

static void test_consume_io_counts_target_read_and_tombstone_failures(void)
{
    blind_zone_record_t record, out;
    blind_zone_diagnostics_t before, after;
    uint32_t sequence = 0U;
    unsigned failure;
    for (failure = 0U; failure < 2U; ++failure) {
        blind_zone_diagnostics_t reset = {0};
        blind_zone_test_set_diagnostics(&reset);
        memset(flash_mem, 0xff, sizeof(flash_mem));
        owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
        record = make_record(900U + failure); append_accepted(&record);
        assert(blind_zone_peek(&out, 1U, &sequence) == 1U);
        assert(blind_zone_consume(sequence, 1U) == BLIND_ZONE_PENDING);
        blind_zone_get_diagnostics(&before);
        if (failure == 0U) {
            fail_read_address = BLIND_DATA_ADDR;
            fail_read_once = true;
        } else {
            fail_after = 0;
        }
        blind_zone_recovery_process();
        blind_zone_get_diagnostics(&after);
        assert(after.consume_io == before.consume_io + 1U);
        assert(after.recovery_retry == before.recovery_retry + 1U);
        fail_after = -1; fail_read_once = false;
        maintenance_ready();
    }
}

static void test_consumed_tombstone_prevents_raw_resurrection(void)
{
    blind_zone_record_t record;
    uint32_t sequence = 0U;
    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    record = make_record(501U); append_accepted(&record);
    record = make_record(502U); append_accepted(&record);
    consume_accepted(1U, 1U);
    memset(flash_mem + BLIND_META_ADDR, 0xff, SECTOR_BYTES);
    owner = EXT_FLASH_OWNER_NONE;
    recover();
    assert(blind_zone_peek(&record, 1U, &sequence) == 1U);
    assert(sequence == 2U && record_value(&record) == 502U);
}

static void test_reconcile_adopts_three_unjournaled_records(void)
{
    uint8_t metadata[SECTOR_BYTES];
    blind_zone_record_t record, out[4];
    uint32_t sequence = 0U;
    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    memcpy(metadata, flash_mem + BLIND_META_ADDR, sizeof(metadata));
    record = make_record(601U); append_accepted(&record);
    forge_record_from_slot0(1U, 2U, 602U);
    forge_record_from_slot0(2U, 3U, 603U);
    memcpy(flash_mem + BLIND_META_ADDR, metadata, sizeof(metadata));
    owner = EXT_FLASH_OWNER_NONE; recover();
    record = make_record(604U); append_accepted(&record);
    assert(blind_zone_peek(out, 4U, &sequence) == 4U && sequence == 1U);
    assert(record_value(&out[0]) == 601U && record_value(&out[1]) == 602U &&
           record_value(&out[2]) == 603U && record_value(&out[3]) == 604U);
}

static void test_full_queue_postcommit_head_read_fault_is_pending(void)
{
    uint32_t i;
    blind_zone_record_t record;
    memset(flash_mem, 0xff, sizeof(flash_mem));
    owner = EXT_FLASH_OWNER_NONE; fail_after = -1; recover();
    for (i = 1U; i <= BLIND_ZONE_LOGICAL_CAPACITY; ++i) {
        record = make_record(i); append_accepted(&record);
    }
    fail_read_address = BLIND_DATA_ADDR;
    fail_read_once = true;
    record = make_record(10001U);
    assert(blind_zone_append(&record) == BLIND_ZONE_PENDING);
    assert(blind_zone_append(&record) == BLIND_ZONE_PENDING);
    maintenance_ready();
    assert(blind_zone_append(&record) == BLIND_ZONE_OK);
    expect_front(2U, 2U);
}

int main(void)
{
    test_exact_capacity_and_event_identity_contract();
    test_fifo_reboot_capacity_and_sector_reclaim();
    test_crc_metadata_selection_and_torn_metadata_scan();
    test_journalled_boot_repairs_damaged_sector_before_ready();
    test_prepared_record_is_finalized_after_reset();
    test_runtime_prepared_finalizes_in_original_nonboundary_slot();
    test_scratch_phase_cut_restores_exact_slots();
    test_repeated_sector_repairs_make_forward_progress();
    test_full_capacity_prepared_and_distributed_repairs_progress();
    test_remote_spare_sector_repair_preserves_full_fifo();
    test_committed_scratch_reboot_preserves_middle_gap_prefix();
    test_capacity_limited_peek_does_not_queue_valid_sector_repair();
    test_contention_and_power_cut_prefixes();
    test_two_cut_hole_then_committed_record_recovery();
    test_diagnostics_contract();
    test_corrupt_head_and_middle_are_quarantined();
    test_structural_middle_corruption_does_not_stall_suffix();
    test_transient_head_read_failure_never_quarantines_valid_head();
    test_consume_tombstones_precede_metadata_and_survive_each_cut();
    test_issued_marker_timeout_later_commit_is_accepted_once();
    test_never_issued_marker_remains_pending_without_loss();
    test_production_batch_sequence_corrupt_middle_survives_reboot();
    test_public_peek_capacity_is_clamped_to_production_max();
    test_full_ring_append_after_peek_makes_ack_stale();
    test_v1_media_fails_closed_and_counts_diagnostic();
    test_diagnostic_counters_saturate();
    test_full_metadata_journal_rollover_power_cuts();
    test_consume_io_counts_target_read_and_tombstone_failures();
    test_consumed_tombstone_prevents_raw_resurrection();
    test_reconcile_adopts_three_unjournaled_records();
    test_full_queue_postcommit_head_read_fault_is_pending();
    puts("test_blind_zone_store: PASS");
    return 0;
}
'''


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        (tmp / "harness.c").write_text(HARNESS, encoding="utf-8")
        executable = tmp / "blind_zone_store.exe"
        subprocess.run(
            [
                compiler(), "-std=c99", "-Wall", "-Wextra", "-Werror",
                "-DBLIND_ZONE_TEST",
                "-I", str(ROOT / "include"),
                str(ROOT / "src" / "blind_zone.c"), str(tmp / "harness.c"),
                "-o", str(executable),
            ],
            check=True,
        )
        subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    main()
