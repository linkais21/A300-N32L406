#include "flash_config.h"
#include "crc32.h"
#include "spi_flash.h"
#include "ext_flash_store.h"
#include "debug_uart.h"
#include <stddef.h>
#include <string.h>

/* ── On-flash slot header ─────────────────────────────────────────────────── */
typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;
    uint16_t data_len;
} legacy_slot_hdr_t;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;
    uint16_t data_len;
    uint32_t generation;
} slot_v3_hdr_t;

#define SLOT_V3_BODY_LEN (sizeof(slot_v3_hdr_t) + sizeof(device_config_t) + 4U)
#define SLOT_V3_TOTAL    (SLOT_V3_BODY_LEN + 4U)
#define CFG_V1_DATA_LEN ((uint16_t)offsetof(device_config_t, pid))
#define CFG_V2_DATA_LEN ((uint16_t)offsetof(device_config_t, backup_auth_code))

typedef enum {
    SLOT_INVALID = 0,
    SLOT_V1,
    SLOT_V2,
    SLOT_V3,
} slot_format_t;

typedef struct {
    slot_format_t format;
    uint32_t generation;
    uint16_t data_len;
} slot_probe_t;

/* ── Live RAM config ──────────────────────────────────────────────────────── */
static device_config_t s_cfg;
static uint32_t s_active_addr;
static uint32_t s_generation;
static bool s_active_valid;

const device_config_t k_config_defaults = {
    .gnss_type          = GNSS_TYPE_TAU804M,
    .server_ip          = "119.147.205.85",
    .server_port        = 9999,
    .backup_ip          = "",
    .backup_port        = 0,
    .heartbeat_s        = 180,
    .report_moving_s    = 30,
    .report_stopped_s   = 180,
    .autoapn_en         = 1,
    .apn                = "",
    .agps_en            = 0,
    .agps_ip            = "0.0.0.0",
    .agps_port          = 0,
    .agnss_user         = "",
    .agnss_pwd          = "",
    .has_acc            = 1,
    .stopdrift_en       = 1,
    .stopdrift_thr      = 50,
    .anglerep_en        = 0,
    .anglerep_angle     = 30,
    .anglerep_speed     = 2,
    .georep_en          = 0,
    .georep_interval    = 30,
    .sends_interval     = 0,
    .cellautogmt_en     = 1,
    .gmt_sign           = 1,
    .gmt_hour           = 8,
    .gmt_min            = 0,
    .phone              = { '0', '0', '0', '0', '0', '0',
                            '0', '0', '0', '0', '0', '0' },
    .auth_code          = "",
    .plate_no           = "",
    .mileage_m          = 0,
    .fota_url           = "",
    .fota_size          = 0,
    .power_alm_en       = 1,
    .sos_alm_en         = 1,
    .lowbat_alm_en      = 1,
    .lowexbat_alm_en    = 1,
    .vib_sens           = 10,
    .pid                = "",
    .terminal_model     = "A300_406",
    .speed_limit_kmh    = 120,
    .sleep_report_mode  = 0,
    .gpsbds_mode        = 2,
    .backup_auth_code   = "",
};

/* ── Read and validate one flash slot ────────────────────────────────────── */
static bool crc_region_locked(uint32_t addr, uint32_t length, uint32_t *crc)
{
    uint8_t chunk[64];
    while (length != 0U) {
        uint32_t count = length > sizeof(chunk) ? sizeof(chunk) : length;
        if (!ext_flash_read(EXT_FLASH_OWNER_CONFIG, addr, chunk, count))
            return false;
        *crc = crc32_update(*crc, chunk, count);
        addr += count;
        length -= count;
    }
    return true;
}

static slot_format_t slot_probe_locked(uint32_t addr, slot_probe_t *out)
{
    legacy_slot_hdr_t legacy;
    uint32_t stored_crc;

    if (out == NULL ||
        !ext_flash_read(EXT_FLASH_OWNER_CONFIG, addr, &legacy, sizeof(legacy))) {
        return SLOT_INVALID;
    }
    if (legacy.magic != CFG_MAGIC) {
        return SLOT_INVALID;
    }

    *out = (slot_probe_t){ .format = SLOT_INVALID,
                           .generation = 0U, .data_len = 0U };

    if (legacy.version == CFG_VERSION &&
        legacy.data_len == sizeof(device_config_t)) {
        uint32_t marker;
        slot_v3_hdr_t hdr;
        uint32_t calc_crc = 0xFFFFFFFFUL;

        if (!ext_flash_read(EXT_FLASH_OWNER_CONFIG, addr, &hdr, sizeof(hdr)) ||
            !crc_region_locked(addr + offsetof(slot_v3_hdr_t, version),
                               8U + sizeof(device_config_t), &calc_crc) ||
            !ext_flash_read(EXT_FLASH_OWNER_CONFIG,
                            addr + sizeof(hdr) + sizeof(device_config_t),
                            &stored_crc, sizeof(stored_crc)) ||
            !ext_flash_read(EXT_FLASH_OWNER_CONFIG,
                            addr + SLOT_V3_BODY_LEN, &marker, sizeof(marker)))
            return SLOT_INVALID;

        if (stored_crc != ~calc_crc || marker != CFG_COMMIT_MARKER)
            return SLOT_INVALID;

        out->generation = hdr.generation;
        out->data_len = hdr.data_len;
        out->format = SLOT_V3;
        return SLOT_V3;
    }

    if (!((legacy.version == 1U && legacy.data_len == CFG_V1_DATA_LEN) ||
          (legacy.version == 2U && legacy.data_len == CFG_V2_DATA_LEN))) {
        return SLOT_INVALID;
    }
    {
        uint32_t calc_crc = 0xFFFFFFFFUL;
        if (!crc_region_locked(addr + sizeof(legacy), legacy.data_len,
                               &calc_crc) ||
            !ext_flash_read(EXT_FLASH_OWNER_CONFIG,
                        addr + sizeof(legacy) + legacy.data_len,
                        &stored_crc, sizeof(stored_crc)) ||
            stored_crc != ~calc_crc)
            return SLOT_INVALID;
    }

    out->format = (legacy.version == 2U) ? SLOT_V2 : SLOT_V1;
    out->data_len = legacy.data_len;
    return out->format;
}

static bool slot_load_locked(uint32_t addr, const slot_probe_t *probe,
                             device_config_t *out)
{
    uint32_t offset;
    if (probe == NULL || out == NULL || probe->format == SLOT_INVALID)
        return false;
    *out = k_config_defaults;
    offset = probe->format == SLOT_V3 ? sizeof(slot_v3_hdr_t) :
                                        sizeof(legacy_slot_hdr_t);
    return ext_flash_read(EXT_FLASH_OWNER_CONFIG, addr + offset, out,
                          probe->data_len);
}

static bool slot_matches_locked(uint32_t addr, const device_config_t *cfg,
                                uint32_t generation)
{
    slot_probe_t probe;
    uint8_t chunk[64];
    const uint8_t *expected = (const uint8_t *)cfg;
    uint32_t offset = 0U;
    if (slot_probe_locked(addr, &probe) != SLOT_V3 ||
        probe.generation != generation)
        return false;
    while (offset < sizeof(*cfg)) {
        uint32_t count = sizeof(*cfg) - offset;
        if (count > sizeof(chunk)) count = sizeof(chunk);
        if (!ext_flash_read(EXT_FLASH_OWNER_CONFIG,
                            addr + sizeof(slot_v3_hdr_t) + offset,
                            chunk, count) ||
            memcmp(chunk, expected + offset, count) != 0)
            return false;
        offset += count;
    }
    return true;
}

/* ── Write one flash slot ─────────────────────────────────────────────────── */
static cfg_store_result_t slot_write_locked(uint32_t addr,
                                            const device_config_t *cfg,
                                            uint32_t generation)
{
    slot_v3_hdr_t hdr = {
        .magic    = CFG_MAGIC,
        .version  = CFG_VERSION,
        .data_len = sizeof(device_config_t),
        .generation = generation,
    };
    uint32_t crc;
    ext_flash_program_result_t marker_result;
    crc = crc32_compute((const uint8_t *)&hdr.version, 8U);
    crc = ~crc32_update(~crc, (const uint8_t *)cfg, sizeof(*cfg));

    if (!ext_flash_erase(EXT_FLASH_OWNER_CONFIG, addr, FLASH_SECTOR_SIZE) ||
        !ext_flash_write_verified(EXT_FLASH_OWNER_CONFIG, addr, &hdr, sizeof(hdr)) ||
        !ext_flash_write_verified(EXT_FLASH_OWNER_CONFIG, addr + sizeof(hdr),
                                  cfg, sizeof(*cfg)) ||
        !ext_flash_write_verified(EXT_FLASH_OWNER_CONFIG,
                                  addr + sizeof(hdr) + sizeof(*cfg),
                                  &crc, sizeof(crc)))
        return CFG_STORE_WRITE_FAILED;

    marker_result = ext_flash_write_result(EXT_FLASH_OWNER_CONFIG,
                                           addr + SLOT_V3_BODY_LEN,
                                           &((uint32_t){ CFG_COMMIT_MARKER }),
                                           sizeof(uint32_t));
    if (marker_result == EXT_FLASH_PROGRAM_NOT_ISSUED)
        return CFG_STORE_WRITE_FAILED;

    return slot_matches_locked(addr, cfg, generation) ? CFG_STORE_OK :
                                                        CFG_STORE_VERIFY_FAILED;
}

static bool generation_newer(uint32_t left, uint32_t right)
{
    return (int32_t)(left - right) > 0;
}

static cfg_store_result_t write_and_activate_locked(
    uint32_t addr, const device_config_t *candidate, uint32_t generation)
{
    cfg_store_result_t result = slot_write_locked(addr, candidate, generation);
    if (result != CFG_STORE_OK) return result;
    s_cfg = *candidate;
    s_active_addr = addr;
    s_generation = generation;
    s_active_valid = true;
    return CFG_STORE_OK;
}

static void log_persist_failure(char slot, uint32_t generation,
                                cfg_store_result_t result)
{
    spi_flash_diagnostics_t diag;
    spi_flash_get_diagnostics(&diag);
    dbg_printf("[CFG] persist failed slot=%c gen=%lu result=%u stage=%s"
               " SR1=%02X SR2=%02X SR3=%02X\r\n",
               slot, (unsigned long)generation, (unsigned int)result,
               spi_flash_failure_name(diag.failure), diag.status1,
               diag.status2, diag.status3);
}

/* ── Public API ───────────────────────────────────────────────────────────── */
void cfg_init(void)
{
    slot_probe_t slot_a;
    slot_probe_t slot_b;
    slot_format_t format_a;
    slot_format_t format_b;

    if (!ext_flash_try_lock(EXT_FLASH_OWNER_CONFIG)) {
        s_cfg = k_config_defaults;
        return;
    }

    s_active_valid = false;
    s_generation = 0U;
    format_a = slot_probe_locked(CFG_FLASH_ADDR_A, &slot_a);
    format_b = slot_probe_locked(CFG_FLASH_ADDR_B, &slot_b);

    if (format_a == SLOT_V3 || format_b == SLOT_V3) {
        const bool use_b = format_b == SLOT_V3 &&
                           (format_a != SLOT_V3 ||
                            generation_newer(slot_b.generation,
                                             slot_a.generation));
        const slot_probe_t *selected = use_b ? &slot_b : &slot_a;
        if (!slot_load_locked(use_b ? CFG_FLASH_ADDR_B : CFG_FLASH_ADDR_A,
                              selected, &s_cfg)) {
            s_cfg = k_config_defaults;
            ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);
            return;
        }
        s_generation = selected->generation;
        s_active_addr = use_b ? CFG_FLASH_ADDR_B : CFG_FLASH_ADDR_A;
        s_active_valid = true;
        dbg_printf("[CFG] loaded v3 slot %c gen=%lu\r\n",
                   use_b ? 'B' : 'A', (unsigned long)s_generation);
        ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);
        return;
    }

    if (format_a == SLOT_V2 || format_b == SLOT_V2 ||
        format_a == SLOT_V1 || format_b == SLOT_V1) {
        const bool use_b = (format_a != SLOT_V2 && format_b == SLOT_V2) ||
                           (format_a == SLOT_INVALID && format_b == SLOT_V1);
        const slot_probe_t *selected = use_b ? &slot_b : &slot_a;
        uint32_t source = use_b ? CFG_FLASH_ADDR_B : CFG_FLASH_ADDR_A;
        uint32_t target = use_b ? CFG_FLASH_ADDR_A : CFG_FLASH_ADDR_B;
        if (!slot_load_locked(source, selected, &s_cfg)) {
            s_cfg = k_config_defaults;
            ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);
            return;
        }
        dbg_printf("[CFG] migrating v%u slot %c\r\n",
                   selected->format == SLOT_V2 ? 2U : 1U,
                   use_b ? 'B' : 'A');
        if (write_and_activate_locked(target, &s_cfg, 1U) == CFG_STORE_OK)
            (void)write_and_activate_locked(source, &s_cfg, 2U);
        ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);
        return;
    }

    dbg_printf("[CFG] no valid config, applying defaults\r\n");
    s_cfg = k_config_defaults;
    {
        cfg_store_result_t result =
            write_and_activate_locked(CFG_FLASH_ADDR_B, &s_cfg, 1U);
        if (result == CFG_STORE_OK) {
            result = write_and_activate_locked(CFG_FLASH_ADDR_A, &s_cfg, 2U);
            if (result == CFG_STORE_OK)
                dbg_printf("[CFG] defaults persisted slot=A gen=2\r\n");
            else
                log_persist_failure('A', 2U, result);
        } else {
            log_persist_failure('B', 1U, result);
        }
    }
    ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);
}

cfg_store_result_t cfg_store_candidate_result(const device_config_t *candidate)
{
    uint32_t target;
    uint32_t generation;
    cfg_store_result_t result;

    if (candidate == NULL || !ext_flash_try_lock(EXT_FLASH_OWNER_CONFIG)) {
        return candidate == NULL ? CFG_STORE_INVALID : CFG_STORE_LOCK_FAILED;
    }

    target = s_active_valid && s_active_addr == CFG_FLASH_ADDR_B ?
             CFG_FLASH_ADDR_A : CFG_FLASH_ADDR_B;
    generation = s_active_valid ? s_generation + 1U : 1U;
    result = write_and_activate_locked(target, candidate, generation);
    ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);
    return result;
}

bool cfg_store_candidate(const device_config_t *candidate)
{
    return cfg_store_candidate_result(candidate) == CFG_STORE_OK;
}

cfg_store_result_t cfg_set_pid_result(const char pid[CFG_PID_LEN])
{
    char previous[CFG_PID_LEN];
    cfg_store_result_t result;
    if (pid == NULL || pid[CFG_PID_LEN - 1U] != '\0') return CFG_STORE_INVALID;
    memcpy(previous, s_cfg.pid, sizeof(previous));
    memcpy(s_cfg.pid, pid, CFG_PID_LEN);
    result = cfg_store_candidate_result(&s_cfg);
    if (result != CFG_STORE_OK) memcpy(s_cfg.pid, previous, sizeof(previous));
    return result;
}

void cfg_save(void)
{
    (void)cfg_store_candidate(&s_cfg);
}

void cfg_factory_reset(void)
{
    s_cfg = k_config_defaults;
    cfg_save();
}

device_config_t *cfg_get(void) { return &s_cfg; }

bool cfg_set_auth_code(uint8_t channel, const char *code)
{
    char previous[CFG_AUTH_LEN];
    char *target;
    size_t length;
    bool stored;

    if (code == NULL)
        return false;
    length = strlen(code);
    if (length >= CFG_AUTH_LEN)
        return false;
    if (channel != 0U && channel != 3U)
        return false;

    target = channel == 0U ? s_cfg.auth_code : s_cfg.backup_auth_code;
    memcpy(previous, target, sizeof(previous));
    memset(target, 0, CFG_AUTH_LEN);
    memcpy(target, code, length);
    stored = cfg_store_candidate(&s_cfg);
    if (!stored) memcpy(target, previous, sizeof(previous));
    return stored;
}

void cfg_set_server(const char *ip, uint16_t port, bool backup)
{
    if (!backup) {
        strncpy(s_cfg.server_ip, ip, CFG_IP_LEN - 1);
        s_cfg.server_port = port;
    } else {
        strncpy(s_cfg.backup_ip, ip, CFG_IP_LEN - 1);
        s_cfg.backup_port = port;
    }
    cfg_save();
}

void cfg_set_heartbeat(uint16_t s)
{
    s_cfg.heartbeat_s = s;
    cfg_save();
}

void cfg_set_report_interval(uint16_t moving_s, uint16_t stopped_s)
{
    s_cfg.report_moving_s  = moving_s;
    s_cfg.report_stopped_s = stopped_s;
    cfg_save();
}

void cfg_set_mileage(uint32_t metres)
{
    s_cfg.mileage_m = metres;
    cfg_save();
}

void cfg_add_mileage(uint32_t delta_m)
{
    s_cfg.mileage_m += delta_m;
    cfg_save();
}
