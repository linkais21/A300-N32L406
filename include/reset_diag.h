#ifndef A300_RESET_DIAG_H
#define A300_RESET_DIAG_H
#include <stdint.h>
typedef enum { RESET_REASON_UNKNOWN=0, RESET_REASON_IWDG, RESET_REASON_WWDG,
 RESET_REASON_SOFTWARE, RESET_REASON_PIN, RESET_REASON_POWER_ON,
 RESET_REASON_LOW_POWER } reset_reason_t;
/* Raw flag bits, reported alongside the decoded reason because more than one
 * can be latched by a single reset. */
#define RESET_FLAG_IWDG       0x01U
#define RESET_FLAG_WWDG       0x02U
#define RESET_FLAG_SOFTWARE   0x04U
#define RESET_FLAG_LOW_POWER  0x08U
#define RESET_FLAG_POWER_ON   0x10U
#define RESET_FLAG_PIN        0x20U
void reset_diag_capture(void);
reset_reason_t reset_diag_reason(void);
uint8_t reset_diag_raw_flags(void);
const char *reset_diag_name(reset_reason_t reason);
#endif
