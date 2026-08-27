#include "flash_config.h"
#include "spi_flash.h"
#include "ext_flash_store.h"
#include "debug_uart.h"
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
    .rtk_en             = 0,
    .rtk_interval       = 5,
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
    .phone              = "000000000000",
    .auth_code          = "",
    .plate_no           = "",
    .mileage_m          = 0,
    .fota_url           = "",
    .fota_size          = 0,
    .vibrate_alm_en     = 1,
    .vibrate_sensitivity = 10,
    .vibrate_debounce   = 5,
    .power_alm_en       = 1,
    .sos_alm_en         = 1,
    .lowbat_alm_en      = 1,
    .lowexbat_alm_en    = 1,
};

/* ── Read and validate one flash slot ────────────────────────────────────── */
static bool slot_read(uint32_t addr, device_config_t *out)
{
    uint8_t raw[SLOT_TOTAL];
    if (!ext_flash_read(addr, raw, SLOT_TOTAL)) return false;

    slot_hdr_t hdr;
    memcpy(&hdr, raw, sizeof(hdr));

    if (hdr.magic   != CFG_MAGIC)              return false;
    if (hdr.version != CFG_VERSION)            return false;
    if (hdr.data_len != sizeof(device_config_t)) return false;

    uint32_t stored_crc;
    memcpy(&stored_crc, raw + sizeof(hdr) + hdr.data_len, 4);
    uint32_t calc_crc = crc32(raw + sizeof(hdr), hdr.data_len);
    if (stored_crc != calc_crc)                return false;

    memcpy(out, raw + sizeof(hdr), sizeof(device_config_t));
    return true;
}

/* ── Write one flash slot ─────────────────────────────────────────────────── */
static bool slot_write(uint32_t addr, const device_config_t *cfg)
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

    if (!ext_flash_try_lock(EXT_FLASH_OWNER_CONFIG)) return false;
    bool ok = ext_flash_erase(addr, FLASH_SECTOR_SIZE) && ext_flash_write_verified(addr, raw, SLOT_TOTAL);
    ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);
    return ok;
}

/* ── Public API ───────────────────────────────────────────────────────────── */
void cfg_init(void)
{
    device_config_t tmp;
    bool ok_a = slot_read(CFG_FLASH_ADDR_A, &tmp);
    bool ok_b = false;

    if (ok_a) {
        s_cfg = tmp;
        dbg_printf("[CFG] loaded from slot A\r\n");
        /* repair slot B if needed */
        device_config_t tmp_b;
        ok_b = slot_read(CFG_FLASH_ADDR_B, &tmp_b);
        if (!ok_b) (void)slot_write(CFG_FLASH_ADDR_B, &s_cfg);
        return;
    }

    ok_b = slot_read(CFG_FLASH_ADDR_B, &tmp);
    if (ok_b) {
        s_cfg = tmp;
        dbg_printf("[CFG] loaded from slot B\r\n");
        (void)slot_write(CFG_FLASH_ADDR_A, &s_cfg);
        return;
    }

    dbg_printf("[CFG] no valid config, applying defaults\r\n");
    cfg_factory_reset();
}

void cfg_save(void)
{
    (void)slot_write(CFG_FLASH_ADDR_A, &s_cfg);
    (void)slot_write(CFG_FLASH_ADDR_B, &s_cfg);
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
