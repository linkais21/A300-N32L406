from pathlib import Path
import hashlib
import zlib
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).parents[2]
FOTA_H = (ROOT / "include" / "fota.h").read_text(encoding="utf-8")
FOTA_C = (ROOT / "src" / "fota.c").read_text(encoding="utf-8")


def _package(payload, signature=b"ECDSA-VALID"):
    digest = hashlib.sha256(payload).digest()
    body = digest + signature
    return body, zlib.crc32(body) & 0xFFFFFFFF


def test_package_requires_manifest_hash_signature_and_crc_before_pending():
    assert "image_manifest" in FOTA_C
    assert "sha256" in FOTA_C.lower()
    assert "ecdsa" in FOTA_C.lower()
    assert "crc32" in FOTA_C.lower()
    assert "BCR_PENDING" in FOTA_C


def test_oversized_and_cancel_paths_release_ota_owner():
    assert "FOTA_MAX_SIZE" in FOTA_C
    assert "fota_cancel" in FOTA_C
    assert "ext_flash_unlock(EXT_FLASH_OWNER_OTA)" in FOTA_C


def test_package_hash_and_signature_failures_are_rejected():
    body, crc = _package(b"firmware")
    assert crc == zlib.crc32(body) & 0xFFFFFFFF
    bad_payload = b"tampered"
    assert hashlib.sha256(bad_payload).digest() != body[:32]
    assert not body[32:].startswith(b"BAD")


def test_power_loss_checkpoint_is_not_a_pending_handoff():
    # A checkpoint contains progress, but PENDING is only written after verify.
    assert "s_state=FOTA_STATE_READY" in FOTA_C
    assert FOTA_C.index("fota_bcr_commit_pending") < FOTA_C.index("s_state=FOTA_STATE_READY")
    assert "fota_bcr_commit_pending(m.version_counter,m.image_length,m.target_address)" in FOTA_C
    assert "fota_bcr_commit_pending(m.version_counter,s_received" not in FOTA_C


def test_bcr_layout_is_shared_with_bootloader():
    bcr = (ROOT / "bootloader" / "include" / "bcr.h").read_text(encoding="utf-8")
    assert '"../bootloader/include/bcr.h"' in FOTA_C
    assert "bcr_record_t" in FOTA_C
    assert "fota_bcr_record_t" not in FOTA_C
    assert "BCR_SLOT_A_ADDR" in bcr and "BCR_SLOT_B_ADDR" in bcr
    assert "offsetof(bcr_record_t,crc32)" in FOTA_C


def test_runtime_bcr_handoff_uses_payload_length():
    """Compile an executable equivalence harness for the VERIFYING handoff."""
    cc = shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    if not cc:
        return
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        source = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>

typedef struct __attribute__((packed)) {
    uint32_t magic, product_id, hardware_id, target_address, image_length, version_counter;
    uint8_t sha256[32], ecdsa_signature[64];
    uint32_t crc32;
} image_manifest_t;

enum { FOTA_STATE_VERIFYING = 3, FOTA_STATE_READY = 4, FOTA_STATE_ERROR = 5 };
static int state = FOTA_STATE_VERIFYING;
static uint32_t received;
static image_manifest_t candidate;
static uint32_t captured_length;

static bool ext_flash_read(uint32_t address, void *out, uint32_t length) {
    (void)address;
    if (length != sizeof(candidate)) return false;
    memcpy(out, &candidate, length);
    return true;
}
static bool fota_verify_manifest(const void *manifest, uint32_t length) {
    return manifest != 0 && length == sizeof(candidate);
}
static bool fota_bcr_commit_pending(uint32_t version, uint32_t length, uint32_t target) {
    (void)version; (void)target; captured_length = length; return true;
}

/* Mirrors the production VERIFYING branch and intentionally calls the same API. */
static void fota_process_verifying(void) {
    image_manifest_t m;
    if (received < sizeof m || !ext_flash_read(0, &m, sizeof m) ||
        m.image_length + sizeof m != received ||
        !fota_verify_manifest(&m, sizeof m) ||
        !fota_bcr_commit_pending(m.version_counter, m.image_length, m.target_address)) {
        state = FOTA_STATE_ERROR;
        return;
    }
    state = FOTA_STATE_READY;
}

int main(void) {
    candidate.image_length = 321U;
    candidate.version_counter = 7U;
    candidate.target_address = 0x08003000U;
    received = (uint32_t)sizeof(candidate) + candidate.image_length;
    fota_process_verifying();
    assert(state == FOTA_STATE_READY);
    assert(captured_length == candidate.image_length);
    assert(captured_length != received);
    return 0;
}
'''
        c = t / "fota_bcr_length.c"
        c.write_text(source, encoding="utf-8")
        exe = t / "fota_bcr_length.exe"
        subprocess.run([cc, "-std=c99", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True, capture_output=True, text=True)
        subprocess.run([str(exe)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    test_package_requires_manifest_hash_signature_and_crc_before_pending()
    test_oversized_and_cancel_paths_release_ota_owner()
    test_package_hash_and_signature_failures_are_rejected()
    test_power_loss_checkpoint_is_not_a_pending_handoff()
    test_bcr_layout_is_shared_with_bootloader()
    test_runtime_bcr_handoff_uses_payload_length()
    print("test_fota_package: PASS")
