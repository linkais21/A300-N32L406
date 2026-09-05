#ifndef A300_RESET_DIAG_H
#define A300_RESET_DIAG_H
typedef enum { RESET_REASON_UNKNOWN=0, RESET_REASON_IWDG, RESET_REASON_WWDG,
 RESET_REASON_SOFTWARE, RESET_REASON_PIN, RESET_REASON_POWER_ON,
 RESET_REASON_LOW_POWER } reset_reason_t;
void reset_diag_capture(void);
reset_reason_t reset_diag_reason(void);
const char *reset_diag_name(reset_reason_t reason);
#endif
