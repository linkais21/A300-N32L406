#ifndef CFG_QUERY_H
#define CFG_QUERY_H
#include <stdbool.h>
#include <stdint.h>
#define CFG_QUERY_HOST "39.108.211.33"
#define CFG_QUERY_PORT 10004U
/* Boot initialization; a live transaction is left intact (not cancelled). */
void cfg_query_init(void);
int cfg_query_start(void);
void cfg_query_process(void);
bool cfg_query_is_busy(void);
bool cfg_query_take_result(int *result);
#endif
