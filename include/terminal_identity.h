#ifndef TERMINAL_IDENTITY_H
#define TERMINAL_IDENTITY_H

#include <stdbool.h>

bool terminal_id_derive(const char *pid, const char *imei, char out[8]);
bool terminal_identity_load(char out[8]);

#endif /* TERMINAL_IDENTITY_H */
