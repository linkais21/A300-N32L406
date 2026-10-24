#ifndef A300_BOOTLOADER_FACTORY_INIT_H
#define A300_BOOTLOADER_FACTORY_INIT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "firmware_layout.h"

#define FACTORY_INIT_PAGE_ADDR       0x08005800UL
#define FACTORY_INIT_PAGE_SIZE       0x00000800UL
#define FACTORY_INIT_MAGIC           0x494E4946UL
#define FACTORY_INIT_FORMAT          1U
#define FACTORY_INIT_GENERATION      1UL
#define FACTORY_INIT_SCOPE_ALL       0x0000000FUL
#define FACTORY_INIT_REQUEST_CRC32   0xAF19BCAAUL
#define FACTORY_INIT_COMMIT_MARKER   0x52455144UL
#define FACTORY_INIT_PENDING         0xFFFFFFFFUL
#define FACTORY_INIT_DONE            0x444F4E45UL

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t format_version;
    uint16_t record_length;
    uint32_t generation;
    uint32_t scope;
    uint32_t crc32;
    uint32_t commit_marker;
    uint32_t completion;
} factory_init_request_t;

typedef enum {
    FACTORY_INIT_RESULT_DEVICE_UNAVAILABLE = -2,
    FACTORY_INIT_RESULT_ERROR = -1,
    FACTORY_INIT_RESULT_ALREADY_DONE = 0,
    FACTORY_INIT_RESULT_APPLIED = 1,
} factory_init_result_t;

_Static_assert(sizeof(factory_init_request_t) == 28U,
               "factory init request wire size changed");
_Static_assert((offsetof(factory_init_request_t, completion) % sizeof(uint32_t)) == 0U,
               "factory init completion must be word aligned");
_Static_assert(FACTORY_INIT_PAGE_ADDR + FACTORY_INIT_PAGE_SIZE <= APP_FLASH_BASE,
               "factory init page overlaps App");

const factory_init_request_t *factory_init_request(void);
factory_init_result_t factory_init_apply(const factory_init_request_t *request);
bool boot_factory_mark_complete(uint32_t completion);
bool boot_ext_device_valid(void);

#endif
