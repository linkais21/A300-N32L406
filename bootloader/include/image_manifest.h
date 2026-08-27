#ifndef A300_IMAGE_MANIFEST_H
#define A300_IMAGE_MANIFEST_H

#include <stdint.h>
#include <stdbool.h>

#define IMAGE_MANIFEST_MAGIC 0x4133464DUL /* A3FM */
#define IMAGE_SHA256_SIZE 32U
#define IMAGE_ECDSA_SIGNATURE_SIZE 64U

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint32_t product_id;
    uint32_t hardware_id;
    uint32_t target_address;
    uint32_t image_length;
    uint32_t version_counter;
    uint8_t sha256[IMAGE_SHA256_SIZE];
    uint8_t ecdsa_signature[IMAGE_ECDSA_SIGNATURE_SIZE];
    uint32_t crc32;
} image_manifest_t;

_Static_assert(sizeof(image_manifest_t) == 124U, "manifest wire size must remain stable");

typedef enum {
    IMAGE_VERIFY_OK = 0,
    IMAGE_VERIFY_INCOMPLETE,
    IMAGE_VERIFY_BOUNDS,
    IMAGE_VERIFY_ID,
    IMAGE_VERIFY_HASH,
    IMAGE_VERIFY_SIGNATURE,
    IMAGE_VERIFY_ROLLBACK,
    IMAGE_VERIFY_CRC
} image_verify_result_t;

#endif
