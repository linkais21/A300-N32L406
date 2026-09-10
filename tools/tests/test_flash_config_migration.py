#!/usr/bin/env python3
"""Host contract test for append-only persisted configuration migration."""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "flash_config.h"
#include "ext_flash_store.h"
#include "spi_flash.h"

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;
    uint16_t data_len;
} test_slot_hdr_t;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;
    uint16_t data_len;
    uint32_t generation;
} test_v3_hdr_t;

#define SLOT_BYTES FLASH_SECTOR_SIZE
#define V1_LEN ((uint16_t)offsetof(device_config_t, pid))
#define V2_LEN ((uint16_t)offsetof(device_config_t, backup_auth_code))
#define V3_LEN ((uint16_t)offsetof(device_config_t, device_api_key))
#define V4_BODY_LEN (sizeof(test_v3_hdr_t) + sizeof(device_config_t) + 4U)
#define DEPLOYED_V1_LEN 684U
#define DEPLOYED_V3_LEN 756U

static uint8_t flash_image[2U * SLOT_BYTES];
static int lock_available;
static uint32_t fail_write_addr;
static uint32_t writes[8];
static size_t write_count;

static uint8_t *slot_at(uint32_t addr)
{
    assert(addr < sizeof(flash_image));
    return &flash_image[addr];
}

static uint32_t test_crc32(const uint8_t *data, uint32_t len)
{
    uint32_t crc = 0xFFFFFFFFUL;
    while (len-- != 0U) {
        int i;
        crc ^= *data++;
        for (i = 0; i < 8; ++i) {
            crc = (crc >> 1) ^ ((crc & 1U) ? 0xEDB88320UL : 0U);
        }
    }
    return ~crc;
}

static void reset_fake_flash(void)
{
    memset(flash_image, 0xFF, sizeof(flash_image));
    lock_available = 1;
    fail_write_addr = UINT32_MAX;
    write_count = 0U;
}

static device_config_t legacy_fixture(const char *server, const char *phone,
                                      gnss_type_t gnss)
{
    device_config_t cfg;
    memset(&cfg, 0xA5, sizeof(cfg));
    memcpy(&cfg, &k_config_defaults, V1_LEN);
    memset(cfg.server_ip, 0, sizeof(cfg.server_ip));
    memcpy(cfg.server_ip, server, strlen(server));
    memset(cfg.phone, 0, sizeof(cfg.phone));
    memcpy(cfg.phone, phone, strlen(phone));
    memset(cfg.backup_ip, 0, sizeof(cfg.backup_ip));
    memcpy(cfg.backup_ip, "808.lhhn.net", sizeof("808.lhhn.net"));
    cfg.backup_port = 8898U;
    cfg.gnss_type = gnss;
    cfg._reserved[0] = 0x3CU;
    return cfg;
}

static device_config_t native_fixture(const char *server, const char *model,
                                      uint16_t speed)
{
    device_config_t cfg = k_config_defaults;
    memset(cfg.server_ip, 0, sizeof(cfg.server_ip));
    memcpy(cfg.server_ip, server, strlen(server));
    memset(cfg.terminal_model, 0, sizeof(cfg.terminal_model));
    memcpy(cfg.terminal_model, model, strlen(model));
    cfg.speed_limit_kmh = speed;
    cfg.sleep_report_mode = 1U;
    cfg.gpsbds_mode = 3U;
    return cfg;
}

static void seed_slot(uint32_t addr, uint16_t version, uint16_t data_len,
                      const device_config_t *cfg, int valid_crc)
{
    test_slot_hdr_t hdr = { CFG_MAGIC, version, data_len };
    uint8_t *raw = slot_at(addr);
    uint32_t crc;

    assert((uint32_t)sizeof(hdr) + data_len + 4U <= SLOT_BYTES);
    memset(raw, 0xFF, SLOT_BYTES);
    memcpy(raw, &hdr, sizeof(hdr));
    memcpy(raw + sizeof(hdr), cfg, data_len);
    crc = test_crc32(raw + sizeof(hdr), data_len);
    if (!valid_crc) {
        crc ^= 1U;
    }
    memcpy(raw + sizeof(hdr) + data_len, &crc, sizeof(crc));
}

static void seed_versioned_slot(uint32_t addr, uint16_t version,
                                uint16_t data_len, uint32_t generation,
                                const device_config_t *cfg, int valid_crc)
{
    test_v3_hdr_t hdr = { CFG_MAGIC, version, data_len, generation };
    uint8_t *raw = slot_at(addr);
    uint32_t crc;
    uint32_t marker = CFG_COMMIT_MARKER;

    assert((uint32_t)sizeof(hdr) + data_len + 8U <= SLOT_BYTES);
    memset(raw, 0xFF, SLOT_BYTES);
    memcpy(raw, &hdr, sizeof(hdr));
    memcpy(raw + sizeof(hdr), cfg, data_len);
    crc = test_crc32(raw + offsetof(test_v3_hdr_t, version),
                     8U + data_len);
    if (!valid_crc) crc ^= 1U;
    memcpy(raw + sizeof(hdr) + data_len, &crc, sizeof(crc));
    memcpy(raw + sizeof(hdr) + data_len + sizeof(crc), &marker,
           sizeof(marker));
}

static void assert_native_slot(uint32_t addr, const device_config_t *want)
{
    const uint8_t *raw = slot_at(addr);
    test_v3_hdr_t hdr;
    uint32_t stored_crc;
    uint32_t marker;

    memcpy(&hdr, raw, sizeof(hdr));
    assert(hdr.magic == CFG_MAGIC);
    assert(hdr.version == 4U);
    assert(hdr.data_len == sizeof(device_config_t));
    memcpy(&stored_crc, raw + sizeof(hdr) + hdr.data_len, sizeof(stored_crc));
    assert(stored_crc == test_crc32(raw + offsetof(test_v3_hdr_t, version),
                                    8U + hdr.data_len));
    memcpy(&marker, raw + V4_BODY_LEN, sizeof(marker));
    assert(marker == CFG_COMMIT_MARKER);
    assert(memcmp(raw + sizeof(hdr), want, sizeof(*want)) == 0);
}

bool ext_flash_try_lock(ext_flash_owner_t owner)
{
    assert(owner == EXT_FLASH_OWNER_CONFIG);
    if (!lock_available) {
        return false;
    }
    lock_available = 0;
    return true;
}

void ext_flash_unlock(ext_flash_owner_t owner)
{
    assert(owner == EXT_FLASH_OWNER_CONFIG);
    assert(!lock_available);
    lock_available = 1;
}

bool ext_flash_read(ext_flash_owner_t owner, uint32_t addr, void *buf,
                    uint32_t len)
{
    assert(owner == EXT_FLASH_OWNER_CONFIG);
    assert(!lock_available);
    assert(len <= SLOT_BYTES);
    assert(addr + len <= sizeof(flash_image));
    memcpy(buf, slot_at(addr), len);
    return true;
}

bool ext_flash_erase(ext_flash_owner_t owner, uint32_t addr, uint32_t len)
{
    assert(owner == EXT_FLASH_OWNER_CONFIG);
    assert(!lock_available);
    assert(len == FLASH_SECTOR_SIZE);
    assert(addr == CFG_FLASH_ADDR_A || addr == CFG_FLASH_ADDR_B);
    memset(slot_at(addr), 0xFF, SLOT_BYTES);
    return true;
}

bool ext_flash_write_verified(ext_flash_owner_t owner, uint32_t addr,
                              const void *buf, uint32_t len)
{
    assert(owner == EXT_FLASH_OWNER_CONFIG);
    assert(!lock_available);
    assert(len <= SLOT_BYTES);
    assert(write_count < sizeof(writes) / sizeof(writes[0]));
    writes[write_count++] = addr;
    if (addr == fail_write_addr) {
        return false;
    }
    {
        const uint8_t *input = (const uint8_t *)buf;
        uint8_t *output = slot_at(addr);
        uint32_t i;
        for (i = 0U; i < len; ++i) output[i] &= input[i];
    }
    return memcmp(slot_at(addr), buf, len) == 0;
}

ext_flash_program_result_t ext_flash_write_result(
    ext_flash_owner_t owner, uint32_t addr, const void *buf, uint32_t len)
{
    assert(owner == EXT_FLASH_OWNER_CONFIG);
    assert(!lock_available);
    assert(len <= SLOT_BYTES);
    assert(write_count < sizeof(writes) / sizeof(writes[0]));
    writes[write_count++] = addr;
    if (addr == fail_write_addr) {
        return EXT_FLASH_PROGRAM_NOT_ISSUED;
    }
    {
        const uint8_t *input = (const uint8_t *)buf;
        uint8_t *output = slot_at(addr);
        uint32_t i;
        for (i = 0U; i < len; ++i) output[i] &= input[i];
    }
    return memcmp(slot_at(addr), buf, len) == 0 ?
           EXT_FLASH_PROGRAM_VERIFIED : EXT_FLASH_PROGRAM_ISSUED_UNCERTAIN;
}

void dbg_printf(const char *fmt, ...)
{
    (void)fmt;
}

void spi_flash_get_diagnostics(spi_flash_diagnostics_t *out)
{
    memset(out, 0, sizeof(*out));
}

const char *spi_flash_failure_name(spi_flash_failure_t failure)
{
    (void)failure;
    return "NONE";
}

static void assert_default_suffix(const device_config_t *cfg)
{
    assert(cfg->pid[0] == '\0');
    assert(strcmp(cfg->terminal_model, "T360-A300") == 0);
    assert(cfg->speed_limit_kmh == 120U);
    assert(cfg->sleep_report_mode == 0U);
    assert(cfg->gpsbds_mode == 2U);
    assert(cfg->backup_auth_code[0] == '\0');
    assert(cfg->device_api_key[0] == '\0');
}

static void test_v3_generation_selection_and_v4_rewrite(void)
{
    device_config_t old_a = native_fixture("old-v3-a", "MODEL-A", 81U);
    device_config_t old_b = native_fixture("old-v3-b", "MODEL-B", 82U);
    device_config_t want = k_config_defaults;
    test_v3_hdr_t header;

    strcpy(old_a.backup_auth_code, "OLD-AUTH-A");
    strcpy(old_b.backup_auth_code, "OLD-AUTH-B");
    strcpy(old_a.fota_url, "http://fota.lhhn.net");
    strcpy(old_b.fota_url, "http://fota.lhhn.net");
    ((uint8_t *)&old_a)[DEPLOYED_V3_LEN - 2U] = 0xA6U;
    ((uint8_t *)&old_a)[DEPLOYED_V3_LEN - 1U] = 0x5AU;
    ((uint8_t *)&old_b)[DEPLOYED_V3_LEN - 2U] = 0x3CU;
    ((uint8_t *)&old_b)[DEPLOYED_V3_LEN - 1U] = 0xC3U;
    memcpy(&want, &old_b, DEPLOYED_V3_LEN);
    reset_fake_flash();
    seed_versioned_slot(CFG_FLASH_ADDR_A, 3U, DEPLOYED_V3_LEN, 41U,
                        &old_a, 1);
    seed_versioned_slot(CFG_FLASH_ADDR_B, 3U, DEPLOYED_V3_LEN, 42U,
                        &old_b, 1);

    cfg_init();

    assert(memcmp(cfg_get(), &old_b, DEPLOYED_V3_LEN) == 0);
    assert(cfg_get()->device_api_key[0] == '\0');
    assert(strcmp(cfg_get()->fota_url, "http://fota.lhhn.net") == 0);
    assert(write_count == 8U);
    assert(writes[0] == CFG_FLASH_ADDR_A);
    assert(writes[4] == CFG_FLASH_ADDR_B);
    assert_native_slot(CFG_FLASH_ADDR_A, &want);
    assert_native_slot(CFG_FLASH_ADDR_B, &want);
    memcpy(&header, slot_at(CFG_FLASH_ADDR_A), sizeof(header));
    assert(header.generation == 43U);
    memcpy(&header, slot_at(CFG_FLASH_ADDR_B), sizeof(header));
    assert(header.generation == 44U);
}

static void assert_legacy_fip_preserved(const device_config_t *cfg)
{
    assert(strcmp(cfg->backup_ip, "808.lhhn.net") == 0);
    assert(cfg->backup_port == 8898U);
}

static void test_v1_a_migrates_other_slot_first(void)
{
    device_config_t old = legacy_fixture("legacy-a", "123456789012",
                                         GNSS_TYPE_ATGM332D_F7N);
    device_config_t want = k_config_defaults;
    memcpy(&want, &old, V1_LEN);
    reset_fake_flash();
    seed_slot(CFG_FLASH_ADDR_A, 1U, V1_LEN, &old, 1);

    cfg_init();

    assert(memcmp(cfg_get(), &old, V1_LEN) == 0);
    assert_legacy_fip_preserved(cfg_get());
    assert_default_suffix(cfg_get());
    assert(write_count == 8U);
    assert(writes[0] == CFG_FLASH_ADDR_B);
    assert(writes[4] == CFG_FLASH_ADDR_A);
    assert_native_slot(CFG_FLASH_ADDR_A, &want);
    assert_native_slot(CFG_FLASH_ADDR_B, &want);
}

static void test_v1_b_migrates_other_slot_first(void)
{
    device_config_t old = legacy_fixture("legacy-b", "210987654321",
                                         GNSS_TYPE_TAU804M);
    device_config_t want = k_config_defaults;
    memcpy(&want, &old, V1_LEN);
    reset_fake_flash();
    seed_slot(CFG_FLASH_ADDR_B, 1U, V1_LEN, &old, 1);

    cfg_init();

    assert(strcmp(cfg_get()->server_ip, "legacy-b") == 0);
    assert_legacy_fip_preserved(cfg_get());
    assert_default_suffix(cfg_get());
    assert(write_count == 8U);
    assert(writes[0] == CFG_FLASH_ADDR_A);
    assert(writes[4] == CFG_FLASH_ADDR_B);
    assert_native_slot(CFG_FLASH_ADDR_A, &want);
    assert_native_slot(CFG_FLASH_ADDR_B, &want);
}

static void test_native_v2_is_preferred_over_v1(void)
{
    device_config_t old = legacy_fixture("legacy-a", "123456789012",
                                         GNSS_TYPE_TAU804M);
    device_config_t native = native_fixture("native-b", "MODEL-B", 88U);
    reset_fake_flash();
    seed_slot(CFG_FLASH_ADDR_A, 1U, V1_LEN, &old, 1);
    seed_slot(CFG_FLASH_ADDR_B, 2U, V2_LEN, &native, 1);

    cfg_init();

    assert(memcmp(cfg_get(), &native, V2_LEN) == 0);
    assert(cfg_get()->backup_auth_code[0] == '\0');
    assert(write_count == 8U);
    assert(writes[0] == CFG_FLASH_ADDR_A);
    assert_native_slot(CFG_FLASH_ADDR_A, &native);
}

static void test_same_format_keeps_a_before_b_precedence(void)
{
    device_config_t native_a = native_fixture("native-a", "MODEL-A", 66U);
    device_config_t native_b = native_fixture("native-b", "MODEL-B", 77U);
    device_config_t legacy_a = legacy_fixture("legacy-a", "123456789012",
                                              GNSS_TYPE_TAU804M);
    device_config_t legacy_b = legacy_fixture("legacy-b", "210987654321",
                                              GNSS_TYPE_ATGM332D_F7N);
    reset_fake_flash();
    seed_slot(CFG_FLASH_ADDR_A, 2U, V2_LEN, &native_a, 1);
    seed_slot(CFG_FLASH_ADDR_B, 2U, V2_LEN, &native_b, 1);
    cfg_init();
    assert(memcmp(cfg_get(), &native_a, V2_LEN) == 0);

    reset_fake_flash();
    seed_slot(CFG_FLASH_ADDR_A, 1U, V1_LEN, &legacy_a, 1);
    seed_slot(CFG_FLASH_ADDR_B, 1U, V1_LEN, &legacy_b, 1);
    cfg_init();
    assert(memcmp(cfg_get(), &legacy_a, V1_LEN) == 0);
}

static void test_corrupt_and_illegal_shapes_are_rejected(void)
{
    device_config_t corrupt = native_fixture("corrupt", "BADCRC", 1U);
    device_config_t illegal = native_fixture("illegal", "BADLEN", 2U);
    reset_fake_flash();
    seed_slot(CFG_FLASH_ADDR_A, 2U, V2_LEN, &corrupt, 0);
    seed_slot(CFG_FLASH_ADDR_B, 1U, (uint16_t)(V1_LEN - 1U), &illegal, 1);

    cfg_init();

    assert(memcmp(cfg_get(), &k_config_defaults, sizeof(*cfg_get())) == 0);
    assert(write_count == 8U);
    assert(writes[0] == CFG_FLASH_ADDR_B);
    assert(writes[4] == CFG_FLASH_ADDR_A);

    reset_fake_flash();
    seed_slot(CFG_FLASH_ADDR_A, 1U, (uint16_t)sizeof(illegal), &illegal, 1);
    seed_slot(CFG_FLASH_ADDR_B, 2U, V1_LEN, &illegal, 1);
    cfg_init();
    assert(memcmp(cfg_get(), &k_config_defaults, sizeof(*cfg_get())) == 0);

    reset_fake_flash();
    seed_slot(CFG_FLASH_ADDR_A, 3U, (uint16_t)sizeof(illegal), &illegal, 1);
    cfg_init();
    assert(memcmp(cfg_get(), &k_config_defaults, sizeof(*cfg_get())) == 0);

    reset_fake_flash();
    seed_versioned_slot(CFG_FLASH_ADDR_A, 3U, DEPLOYED_V3_LEN, 9U,
                        &corrupt, 0);
    seed_versioned_slot(CFG_FLASH_ADDR_B, 3U,
                        (uint16_t)(DEPLOYED_V3_LEN + 1U),
                        10U, &illegal, 1);
    cfg_init();
    assert(memcmp(cfg_get(), &k_config_defaults, sizeof(*cfg_get())) == 0);
}

static void test_failed_other_slot_preserves_v1_source(void)
{
    device_config_t old = legacy_fixture("survivor", "123456789012",
                                         GNSS_TYPE_TAU804M);
    uint8_t source_before[SLOT_BYTES];
    reset_fake_flash();
    seed_slot(CFG_FLASH_ADDR_A, 1U, V1_LEN, &old, 1);
    memcpy(source_before, slot_at(CFG_FLASH_ADDR_A), sizeof(source_before));
    fail_write_addr = CFG_FLASH_ADDR_B;

    cfg_init();

    assert(write_count == 1U);
    assert(writes[0] == CFG_FLASH_ADDR_B);
    assert(memcmp(slot_at(CFG_FLASH_ADDR_A), source_before,
                  sizeof(source_before)) == 0);
}

static void test_failed_other_slot_preserves_v3_source(void)
{
    device_config_t old = native_fixture("v3-survivor", "V3-SAFE", 91U);
    uint8_t source_before[SLOT_BYTES];
    static const char key[CFG_DEVICE_API_KEY_LEN] = "1234567890ABCDEF";

    strcpy(old.backup_auth_code, "V3-BACKUP-AUTH");
    ((uint8_t *)&old)[DEPLOYED_V3_LEN - 2U] = 0x96U;
    ((uint8_t *)&old)[DEPLOYED_V3_LEN - 1U] = 0x69U;
    reset_fake_flash();
    seed_versioned_slot(CFG_FLASH_ADDR_B, 3U, DEPLOYED_V3_LEN, 71U,
                        &old, 1);
    memcpy(source_before, slot_at(CFG_FLASH_ADDR_B), sizeof(source_before));
    fail_write_addr = CFG_FLASH_ADDR_A;

    cfg_init();

    assert(memcmp(cfg_get(), &old, DEPLOYED_V3_LEN) == 0);
    assert(cfg_get()->device_api_key[0] == '\0');
    assert(write_count == 1U);
    assert(writes[0] == CFG_FLASH_ADDR_A);
    assert(memcmp(slot_at(CFG_FLASH_ADDR_B), source_before,
                  sizeof(source_before)) == 0);

    write_count = 0U;
    fail_write_addr = CFG_FLASH_ADDR_A + V4_BODY_LEN;
    assert(cfg_set_device_api_key_result(key) == CFG_STORE_WRITE_FAILED);
    assert(write_count == 4U);
    assert(writes[0] == CFG_FLASH_ADDR_A);
    assert(writes[3] == CFG_FLASH_ADDR_A + V4_BODY_LEN);
    assert(cfg_get()->device_api_key[0] == '\0');
    assert(memcmp(slot_at(CFG_FLASH_ADDR_B), source_before,
                  sizeof(source_before)) == 0);

    write_count = 0U;
    fail_write_addr = CFG_FLASH_ADDR_A;
    cfg_init();
    assert(memcmp(cfg_get(), &old, DEPLOYED_V3_LEN) == 0);
    assert(cfg_get()->device_api_key[0] == '\0');
    assert(write_count == 1U && writes[0] == CFG_FLASH_ADDR_A);
    assert(memcmp(slot_at(CFG_FLASH_ADDR_B), source_before,
                  sizeof(source_before)) == 0);
}

static void test_candidate_store_contract(void)
{
    device_config_t live_seed = native_fixture("live", "LIVE", 77U);
    device_config_t candidate = native_fixture("candidate", "NEXT", 99U);
    device_config_t live_before;

    reset_fake_flash();
    seed_slot(CFG_FLASH_ADDR_A, 2U, V2_LEN, &live_seed, 1);
    seed_slot(CFG_FLASH_ADDR_B, 2U, V2_LEN, &live_seed, 1);
    cfg_init();
    live_before = *cfg_get();
    write_count = 0U;

    lock_available = 0;
    assert(!cfg_store_candidate(&candidate));
    assert(memcmp(cfg_get(), &live_before, sizeof(live_before)) == 0);
    assert(write_count == 0U);
    lock_available = 1;
    assert(!cfg_store_candidate(NULL));
    assert(write_count == 0U);

    fail_write_addr = CFG_FLASH_ADDR_B;
    assert(!cfg_store_candidate(&candidate));
    assert(write_count == 1U && writes[0] == CFG_FLASH_ADDR_B);
    assert(memcmp(cfg_get(), &live_before, sizeof(live_before)) == 0);

    write_count = 0U;
    fail_write_addr = CFG_FLASH_ADDR_B + V4_BODY_LEN;
    assert(!cfg_store_candidate(&candidate));
    assert(write_count == 4U);
    assert(writes[0] == CFG_FLASH_ADDR_B);
    assert(writes[3] == CFG_FLASH_ADDR_B + V4_BODY_LEN);
    assert(memcmp(cfg_get(), &live_before, sizeof(live_before)) == 0);

    fail_write_addr = UINT32_MAX;
    write_count = 0U;
    assert(cfg_store_candidate(&candidate));
    assert(write_count == 4U);
    assert(writes[0] == CFG_FLASH_ADDR_B);
    assert_native_slot(CFG_FLASH_ADDR_B, &candidate);
    assert(memcmp(cfg_get(), &candidate, sizeof(candidate)) == 0);
}

static void test_device_api_key_store_rolls_back_on_failure(void)
{
    static const char first[CFG_DEVICE_API_KEY_LEN] = "1234567890ABCDEF";
    static const char second[CFG_DEVICE_API_KEY_LEN] = "ZYXWVUTSRQPONMLK";
    static const char too_short[CFG_DEVICE_API_KEY_LEN] = "1234567890ABCDE";
    device_config_t before;

    reset_fake_flash();
    cfg_init();
    write_count = 0U;
    assert(cfg_set_device_api_key_result(first) == CFG_STORE_OK);
    assert(strcmp(cfg_get()->device_api_key, first) == 0);
    before = *cfg_get();

    write_count = 0U;
    assert(cfg_set_device_api_key_result(cfg_get()->device_api_key) ==
           CFG_STORE_OK);
    assert(strcmp(cfg_get()->device_api_key, first) == 0);
    before = *cfg_get();

    fail_write_addr = CFG_FLASH_ADDR_B;
    assert(cfg_set_device_api_key_result(second) == CFG_STORE_WRITE_FAILED);
    assert(memcmp(cfg_get(), &before, sizeof(before)) == 0);
    assert(strcmp(cfg_get()->device_api_key, first) == 0);
    assert(cfg_set_device_api_key_result(too_short) ==
           CFG_STORE_INVALID);
    assert(memcmp(cfg_get(), &before, sizeof(before)) == 0);
}

int main(void)
{
    assert(CFG_VERSION == 4U);
    assert(CFG_DEVICE_API_KEY_LEN == 32U);
    assert(CFG_PID_LEN == 12U);
    assert(CFG_MODEL_LEN == 21U);
    assert(V1_LEN == DEPLOYED_V1_LEN);
    assert(V3_LEN == DEPLOYED_V3_LEN);
    assert(k_config_defaults.backup_ip[0] == '\0');
    assert(k_config_defaults.backup_port == 0U);
    assert(strcmp(k_config_defaults.fota_url, "http://fota.lhhn.net") == 0);
    test_v1_a_migrates_other_slot_first();
    test_v1_b_migrates_other_slot_first();
    test_native_v2_is_preferred_over_v1();
    test_same_format_keeps_a_before_b_precedence();
    test_v3_generation_selection_and_v4_rewrite();
    test_corrupt_and_illegal_shapes_are_rejected();
    test_failed_other_slot_preserves_v1_source();
    test_failed_other_slot_preserves_v3_source();
    test_candidate_store_contract();
    test_device_api_key_store_rolls_back_on_failure();
    return 0;
}
'''


def find_compiler():
    for candidate in ("gcc", "cc"):
        found = shutil.which(candidate)
        if found:
            return found
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            executable = pathlib.Path(directory) / (candidate + ".exe")
            if executable.is_file():
                return str(executable)
    return None


def main():
    compiler = find_compiler()
    if compiler is None:
        if os.environ.get("REQUIRE_GCC") == "1":
            print("test_flash_config_migration: FAIL (no C compiler available)")
            return 1
        print("test_flash_config_migration: SKIP (no C compiler available)")
        return 0

    with tempfile.TemporaryDirectory(prefix="flash_config_migration_") as temp_dir:
        temp = pathlib.Path(temp_dir)
        harness = temp / "flash_config_migration_harness.c"
        binary = temp / "flash_config_migration_harness.exe"
        harness.write_text(HARNESS, encoding="utf-8")
        command = [
            compiler, "-std=c99", "-Wall", "-Wextra", "-Werror",
            "-I", str(ROOT / "include"), str(harness),
            str(ROOT / "src" / "flash_config.c"), str(ROOT / "src" / "crc32.c"),
            "-o", str(binary),
        ]
        build = subprocess.run(command, cwd=ROOT, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if build.returncode != 0:
            print(build.stdout, end="")
            print("test_flash_config_migration: FAIL (C harness did not compile)")
            return build.returncode
        run = subprocess.run([str(binary)], cwd=ROOT, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if run.returncode != 0:
            print(run.stdout, end="")
            print("test_flash_config_migration: FAIL (C harness assertion)")
            return run.returncode

    print("test_flash_config_migration: C99 -Wall -Wextra -Werror PASS")
    print("test_flash_config_migration: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
