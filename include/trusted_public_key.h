#ifndef A300_TRUSTED_PUBLIC_KEY_H
#define A300_TRUSTED_PUBLIC_KEY_H

#include <stdint.h>

/* Trust anchor for OTA package signatures.
 *
 * The FOTA platform re-signs every uploaded package with its own private key
 * (fota.security.signing-private-key), so the device must trust the platform's
 * public key. Source: the reference G452 bootloader's OTA_PUBLIC_KEY.
 * Independently verified on 2026-09-12 against the live platform's V3.035
 * digest/signature (tools/tests/fixtures/platform_v3035_signature.json).
 * The former recovered d90bf067... key fails that same signature. Historical
 * V3.023 notes are not evidence for trusting a recovered candidate key.
 * App and bootloader share this header through src/firmware_signature.c;
 * existing devices with the wrong key require a coordinated SWD repair.
 *
 * Encoding: secp256r1, 32-byte big-endian X followed by 32-byte big-endian Y.
 */
#define TRUSTED_KEY_LABEL "FOTA-PLATFORM-P256"
#define TRUSTED_SIGNING_KEY_ID 1UL
#define TRUSTED_PUBLIC_KEY_SIZE 64U

static const uint8_t trusted_public_key[TRUSTED_PUBLIC_KEY_SIZE] = {
    0xb6, 0x2d, 0x2b, 0x71, 0xc4, 0x11, 0x57, 0x95,
    0xef, 0x95, 0x6d, 0x3e, 0x7d, 0x6d, 0x3e, 0xe3,
    0xfa, 0x79, 0x19, 0x06, 0x48, 0x7d, 0xa4, 0x48,
    0x5f, 0x9b, 0x28, 0x28, 0x3a, 0x47, 0x86, 0x2e,
    0x32, 0xbe, 0xff, 0xae, 0xab, 0x96, 0x0c, 0x88,
    0x84, 0x27, 0xf7, 0x2d, 0xe8, 0xdf, 0x95, 0xe0,
    0x6b, 0x73, 0xe1, 0x11, 0xd2, 0x42, 0x04, 0xf0,
    0x35, 0xa5, 0x37, 0x48, 0xb0, 0x5a, 0x60, 0x97,
};

#endif /* A300_TRUSTED_PUBLIC_KEY_H */
