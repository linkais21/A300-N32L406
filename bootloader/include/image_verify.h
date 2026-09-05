#ifndef A300_IMAGE_VERIFY_H
#define A300_IMAGE_VERIFY_H

#include "image_manifest.h"

image_verify_result_t verify_candidate(const image_manifest_t *manifest);
bool verify_external_manifest(const image_manifest_t *manifest, uint32_t base_address);
uint32_t image_crc32(const void *data, uint32_t length);
void image_signature_digest(const image_manifest_t *manifest,
                            uint8_t out[IMAGE_SHA256_SIZE]);

/* Implemented by the fail-closed N32L406 platform. */
bool boot_ext_read(uint32_t address, void *data, uint32_t length);
bool boot_ext_write(uint32_t address, const void *data, uint32_t length);
bool boot_ext_erase(uint32_t address, uint32_t length);
bool boot_ext_is_complete(uint32_t address, uint32_t length);
bool boot_compute_internal_hash(uint32_t address, uint32_t length, uint8_t hash[IMAGE_SHA256_SIZE]);
uint32_t boot_rollback_counter(void);

#endif
