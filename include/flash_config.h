#ifndef FLASH_CONFIG_H
#define FLASH_CONFIG_H

#include <stdint.h>
#include <stdbool.h>
#include "ext_flash_layout.h"
#include "agnss_storage.h"

/*
 * Flash config layout on BY25Q16 (2 MB):
 *   Slot A: sector 0  @ 0x000000 (4 KB)
 *   Slot B: sector 1  @ 0x001000 (4 KB)  — redundant backup
 *   FOTA area:        @ 0x010000 (1 MB)  — firmware download buffer
 *
 * v3 slot: [magic(4)] [version(2)] [len(2)] [generation(4)]
 *          [data(N)] [crc32(4)] [commit_marker(4)]
 */

#define CFG_FLASH_ADDR_A    EXT_FLASH_CONFIG_SLOT_A_ADDR
#define CFG_FLASH_ADDR_B    EXT_FLASH_CONFIG_SLOT_B_ADDR
#define CFG_MAGIC           0xA3001406UL
#define CFG_VERSION         3U
#define CFG_COMMIT_MARKER   0x43464733UL

/* String field max lengths */
#define CFG_IP_LEN      64
#define CFG_APN_LEN     32
#define CFG_USER_LEN    32
#define CFG_PASS_LEN    32
#define CFG_PHONE_LEN   12
#define CFG_AUTH_LEN    32
#define CFG_PLATE_LEN   16
#define CFG_AGNSS_USER_LEN 64
#define CFG_AGNSS_PWD_LEN  64
#define CFG_PID_LEN         12
#define CFG_MODEL_LEN       21

typedef struct {
    gnss_type_t gnss_type;
    /* ── Server ──────────────────────────────────────────────────────────── */
    char     server_ip[CFG_IP_LEN];
    uint16_t server_port;
    char     backup_ip[CFG_IP_LEN];
    uint16_t backup_port;

    /* ── Timing ──────────────────────────────────────────────────────────── */
    uint16_t heartbeat_s;       /* 60–600 s */
    uint16_t report_moving_s;   /* A: moving interval */
    uint16_t report_stopped_s;  /* B: stopped interval */

    /* ── Modem ───────────────────────────────────────────────────────────── */
    uint8_t  autoapn_en;
    char     apn[CFG_APN_LEN];
    char     apn_user[CFG_USER_LEN];
    char     apn_pass[CFG_PASS_LEN];

    /* ── AGPS ────────────────────────────────────────────────────────────── */
    uint8_t  agps_en;
    char     agps_ip[CFG_IP_LEN];
    uint16_t agps_port;
    char     agnss_user[CFG_AGNSS_USER_LEN];
    char     agnss_pwd[CFG_AGNSS_PWD_LEN];

    /* ── Alarms ──────────────────────────────────────────────────────────── */
    uint8_t  power_alm_en;
    uint8_t  sos_alm_en;
    uint8_t  sos_mode;          /* 0–3 */
    uint8_t  lowbat_alm_en;
    uint8_t  lowexbat_alm_en;

    /* ── Input / motion ──────────────────────────────────────────────────── */
    uint8_t  has_acc;           /* 0=no ACC wire 1=yes */
    uint8_t  stopdrift_en;
    uint16_t stopdrift_thr;     /* 10–1000 cm */
    uint8_t  anglerep_en;
    uint8_t  anglerep_angle;    /* 1–180 deg */
    uint8_t  anglerep_speed;    /* 2–5 */
    uint8_t  georep_en;
    uint16_t georep_interval;   /* 10–600 s */

    /* ── Reporting ───────────────────────────────────────────────────────── */
    uint16_t sends_interval;    /* 0–300 s */
    uint8_t  cellautogmt_en;
    int8_t   gmt_sign;          /* +1=E -1=W */
    uint8_t  gmt_hour;          /* 0–12 */
    uint8_t  gmt_min;           /* 0–59 */

    /* ── Device identity ─────────────────────────────────────────────────── */
    char     phone[CFG_PHONE_LEN];
    char     auth_code[CFG_AUTH_LEN];
    char     plate_no[CFG_PLATE_LEN];

    /* ── Mileage (odometer) ──────────────────────────────────────────────── */
    uint32_t mileage_m;         /* total metres driven */

    /* ── FOTA ────────────────────────────────────────────────────────────── */
    char     fota_url[128];     /* HTTP URL for firmware */
    uint32_t fota_size;         /* expected size, 0=unknown */

    /* Product vibration sensitivity 1..50 (doc: smaller = more sensitive).
     * Carved out of the former _reserved block so the v1/v2 byte prefixes and
     * sizeof(device_config_t) are unchanged and no slot migration is needed.
     * 0 means "never configured" and falls back to the shipped default. */
    uint8_t  vib_sens;
    uint8_t  _reserved[31];

    /* v2 F39 settings; append-only after the complete v1 prefix */
    char     pid[CFG_PID_LEN];
    char     terminal_model[CFG_MODEL_LEN];
    uint16_t speed_limit_kmh;
    uint8_t  sleep_report_mode;
    uint8_t  gpsbds_mode;

    /* v3 append-only field; the deployed v2 byte prefix ends before this. */
    char     backup_auth_code[CFG_AUTH_LEN];
} device_config_t;

typedef enum {
    CFG_STORE_OK = 0,
    CFG_STORE_INVALID,
    CFG_STORE_LOCK_FAILED,
    CFG_STORE_WRITE_FAILED,
    CFG_STORE_VERIFY_FAILED,
} cfg_store_result_t;

/* Default values applied on factory reset */
extern const device_config_t k_config_defaults;

void     cfg_init(void);                /* load from flash; apply defaults if invalid */
void     cfg_save(void);                /* write to both slots */
bool     cfg_store_candidate(const device_config_t *candidate);
cfg_store_result_t cfg_store_candidate_result(const device_config_t *candidate);
cfg_store_result_t cfg_set_pid_result(const char pid[CFG_PID_LEN]);
bool     cfg_set_auth_code(uint8_t channel, const char *code);
void     cfg_factory_reset(void);       /* restore defaults and save */

device_config_t *cfg_get(void);         /* pointer to live RAM copy */

/* Convenience setters — each calls cfg_save() */
void cfg_set_server(const char *ip, uint16_t port, bool backup);
void cfg_set_heartbeat(uint16_t s);
void cfg_set_report_interval(uint16_t moving_s, uint16_t stopped_s);
void cfg_set_mileage(uint32_t metres);
void cfg_add_mileage(uint32_t delta_m);

#endif /* FLASH_CONFIG_H */
