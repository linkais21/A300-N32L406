#ifndef A300_IMAGE_VERIFY_H
#define A300_IMAGE_VERIFY_H

#include "image_manifest.h"
#include "boot_contract.h"

image_verify_result_t verify_candidate(const image_manifest_t *manifest);
bool verify_external_manifest(const image_manifest_t *manifest, uint32_t base_address,
                              uint32_t authorization_address);
bool verify_external_manifest_for_promotion(const image_manifest_t *manifest,
                                            uint32_t base_address,
                                            uint32_t authorization_address);
bool verify_legacy_package(uint32_t base_address, uint32_t region_end,
                           legacy_image_manifest_t *out);
void legacy_image_signature_digest(const legacy_image_manifest_t *manifest,
                                   uint8_t digest[IMAGE_SHA256_SIZE]);
bool boot_authorization_read_at(uint32_t address, fota_authorization_t *out);
uint32_t image_crc32(const void *data, uint32_t length);
bool boot_authorization_load(fota_authorization_t *out);

/* Implemented by the fail-closed N32L406 platform. */
bool boot_ext_read(uint32_t address, void *data, uint32_t length);
bool boot_ext_write(uint32_t address, const void *data, uint32_t length);
bool boot_ext_erase(uint32_t address, uint32_t length);
bool boot_ext_is_complete(uint32_t address, uint32_t length);
bool boot_compute_internal_hash(uint32_t address, uint32_t length, uint8_t hash[IMAGE_SHA256_SIZE]);
bool boot_rollback_counter(uint32_t *out);
bool boot_app_vectors_valid(uint32_t address);
void boot_watchdog_feed(void);

#endif
