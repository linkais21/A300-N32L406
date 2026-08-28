#ifndef F39_CONFIG_ADAPTER_H
#define F39_CONFIG_ADAPTER_H

#include <stdbool.h>
#include <stdint.h>

#include "f39_command.h"
#include "flash_config.h"

typedef bool (*f39_persist_config_fn)(const device_config_t *candidate,
                                      void *context);

enum {
    F39_EFFECT_NONE               = 0U,
    F39_EFFECT_TIMER_REFRESH      = (1UL << 0),
    F39_EFFECT_NETWORK_RECONNECT  = (1UL << 1),
    F39_EFFECT_GNSS_REFRESH       = (1UL << 2),
    F39_EFFECT_JT808_REREGISTER   = (1UL << 3),
    F39_EFFECT_REMAINING_REFRESH  = (1UL << 4)
};

typedef struct {
    device_config_t candidate;
    device_config_t *live;
    f39_persist_config_fn persist;
    void *persist_context;
    uint32_t effects;
    bool prepared;
} f39_transaction_t;

void f39_transaction_init(f39_transaction_t *transaction,
                          device_config_t *live,
                          f39_persist_config_fn persist,
                          void *persist_context);
bool f39_prepare_config(const f39_request_t *request,
                        const device_config_t *current,
                        f39_transaction_t *transaction);
f39_result_t f39_commit_config(f39_transaction_t *transaction);

#endif
