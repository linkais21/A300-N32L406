#include "flash_config.h"
#include "spi_flash.h"
#include "ext_flash_store.h"
#include "debug_uart.h"
#include <stddef.h>
#include <string.h>

/* ── CRC-32 (IEEE 802.3 polynomial) ──────────────────────────────────────── */
static uint32_t crc32(const uint8_t *data, uint32_t len)
{
    uint32_t crc = 0xFFFFFFFFUL;
    while (len--) {
        crc ^= *data++;
        for (int i = 0; i < 8; i++)
            crc = (crc >> 1) ^ (crc & 1 ? 0xEDB88320UL : 0);
    }
    return ~crc;
}

/* ── On-flash slot header ─────────────────────────────────────────────────── */
typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;
    uint16_t data_len;
} slot_hdr_t;

#define SLOT_TOTAL  (sizeof(slot_hdr_t) + sizeof(device_config_t) + 4)
#define CFG_V1_DATA_LEN ((uint16_t)offsetof(device_config_t, pid))

typedef enum {
    SLOT_INVALID = 0,
    SLOT_V1,
    SLOT_V2,
} slot_format_t;

/* ── Live RAM config ──────────────────────────────────────────────────────── */
static device_config_t s_cfg;

const device_config_t k_config_defaults = {
    .server_ip          = "119.147.205.85",
    .server_port        = 9999,
    .backup_ip          = "808.lhhn.net",
    .backup_port        = 8898,
    .heartbeat_s        = 60,
    .report_moving_s    = 30,
    .report_stopped_s   = 60,
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
    .pid                = "",
    .terminal_model     = "A300_406",
    .speed_limit_kmh    = 120,
    .sleep_report_mode  = 0,
    .gpsbds_mode        = 2,
};

/* ── Read and validate one flash slot ────────────────────────────────────── */
static slot_format_t slot_read_locked(uint32_t addr, device_config_t *out)
{
    uint8_t raw[SLOT_TOTAL];
    if (!ext_flash_read(EXT_FLASH_OWNER_CONFIG, addr, raw, SLOT_TOTAL)) {
        return SLOT_INVALID;
    }

    slot_hdr_t hdr;
    memcpy(&hdr, raw, sizeof(hdr));

    if (hdr.magic != CFG_MAGIC) {
        return SLOT_INVALID;
    }
    if (!((hdr.version == 1U && hdr.data_len == CFG_V1_DATA_LEN) ||
          (hdr.version == CFG_VERSION &&
           hdr.data_len == sizeof(device_config_t)))) {
        return SLOT_INVALID;
    }

    uint32_t stored_crc;
    memcpy(&stored_crc, raw + sizeof(hdr) + hdr.data_len, 4);
    uint32_t calc_crc = crc32(raw + sizeof(hdr), hdr.data_len);
    if (stored_crc != calc_crc) {
        return SLOT_INVALID;
    }

    *out = k_config_defaults;
    memcpy(out, raw + sizeof(hdr), hdr.data_len);
    return (hdr.version == CFG_VERSION) ? SLOT_V2 : SLOT_V1;
}

/* ── Write one flash slot ─────────────────────────────────────────────────── */
static bool slot_write_locked(uint32_t addr, const device_config_t *cfg)
{
    uint8_t raw[SLOT_TOTAL];
    memset(raw, 0xFF, sizeof(raw));

    slot_hdr_t hdr = {
        .magic    = CFG_MAGIC,
        .version  = CFG_VERSION,
        .data_len = sizeof(device_config_t),
    };
    memcpy(raw, &hdr, sizeof(hdr));
    memcpy(raw + sizeof(hdr), cfg, sizeof(device_config_t));

    uint32_t crc = crc32(raw + sizeof(hdr), sizeof(device_config_t));
    memcpy(raw + sizeof(hdr) + sizeof(device_config_t), &crc, 4);

    return ext_flash_erase(EXT_FLASH_OWNER_CONFIG, addr, FLASH_SECTOR_SIZE) &&
           ext_flash_write_verified(EXT_FLASH_OWNER_CONFIG, addr, raw, SLOT_TOTAL);
}

/* ── Public API ───────────────────────────────────────────────────────────── */
void cfg_init(void)
{
    device_config_t cfg_a;
    device_config_t cfg_b;
    slot_format_t format_a;
    slot_format_t format_b;

    if (!ext_flash_try_lock(EXT_FLASH_OWNER_CONFIG)) {
        s_cfg = k_config_defaults;
        return;
    }

    format_a = slot_read_locked(CFG_FLASH_ADDR_A, &cfg_a);
    format_b = slot_read_locked(CFG_FLASH_ADDR_B, &cfg_b);

    if (format_a == SLOT_V2) {
        s_cfg = cfg_a;
        dbg_printf("[CFG] loaded from slot A\r\n");
        if (format_b != SLOT_V2) {
            (void)slot_write_locked(CFG_FLASH_ADDR_B, &s_cfg);
        }
        ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);
        return;
    }

    if (format_b == SLOT_V2) {
        s_cfg = cfg_b;
        dbg_printf("[CFG] loaded from slot B\r\n");
        (void)slot_write_locked(CFG_FLASH_ADDR_A, &s_cfg);
        ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);
        return;
    }

    if (format_a == SLOT_V1) {
        s_cfg = cfg_a;
        dbg_printf("[CFG] migrating slot A from v1\r\n");
        if (slot_write_locked(CFG_FLASH_ADDR_B, &s_cfg)) {
            (void)slot_write_locked(CFG_FLASH_ADDR_A, &s_cfg);
        }
        ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);
        return;
    }

    if (format_b == SLOT_V1) {
        s_cfg = cfg_b;
        dbg_printf("[CFG] migrating slot B from v1\r\n");
        if (slot_write_locked(CFG_FLASH_ADDR_A, &s_cfg)) {
            (void)slot_write_locked(CFG_FLASH_ADDR_B, &s_cfg);
        }
        ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);
        return;
    }

    dbg_printf("[CFG] no valid config, applying defaults\r\n");
    s_cfg = k_config_defaults;
    (void)slot_write_locked(CFG_FLASH_ADDR_B, &s_cfg);
    (void)slot_write_locked(CFG_FLASH_ADDR_A, &s_cfg);
    ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);
}

bool cfg_store_candidate(const device_config_t *candidate)
{
    bool ok_b;
    bool ok_a = false;

    if (candidate == NULL || !ext_flash_try_lock(EXT_FLASH_OWNER_CONFIG)) {
        return false;
    }

    ok_b = slot_write_locked(CFG_FLASH_ADDR_B, candidate);
    if (ok_b) {
        ok_a = slot_write_locked(CFG_FLASH_ADDR_A, candidate);
    }
    ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);
    return ok_b && ok_a;
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
