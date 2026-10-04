#include "firmware_signature.h"
#include "trusted_public_key.h"
#include "uECC.h"

bool firmware_signature_verify(const uint8_t digest[32],
                               const uint8_t signature[64])
{
    if (digest == 0 || signature == 0) return false;
    return uECC_verify(trusted_public_key, digest, 32U, signature,
                       uECC_secp256r1()) == 1;
}
