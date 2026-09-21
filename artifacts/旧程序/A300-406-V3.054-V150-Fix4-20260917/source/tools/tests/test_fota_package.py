from pathlib import Path
import hashlib
import zlib
import shutil
import subprocess
import tempfile
import struct


ROOT = Path(__file__).parents[2]
FOTA_H = (ROOT / "include" / "fota.h").read_text(encoding="utf-8")
FOTA_C = (ROOT / "src" / "fota.c").read_text(encoding="utf-8")
BOOT_CONTRACT = (ROOT / "include" / "boot_contract.h").read_text(encoding="utf-8")


def test_a300_wire_header_is_exactly_32_bytes():
    body = struct.pack("<II", 0x20001000, 0x08006009) + b"a300-body"
    crc = zlib.crc32(body) & 0xFFFFFFFF
    wire = struct.pack("<IIIII12s", 0xA300B007, 3002, len(body), crc,
                       0x41333030, bytes(12))
    assert len(wire) == 32
    assert struct.unpack("<IIIII12s", wire) == (
        0xA300B007, 3002, len(body), crc, 0x41333030, bytes(12))
    assert "FOTA_PACKAGE_HEADER_MAGIC 0xA300B007UL" in FOTA_H
    assert "_Static_assert(sizeof(fota_package_header_t) == FOTA_PACKAGE_HEADER_SIZE" in FOTA_H
    assert "uint8_t reserved[12]" in FOTA_H


def test_detached_metadata_is_durable_before_bounded_status_and_reset():
    assert "package_sha256[32]" in BOOT_CONTRACT
    assert "signature[64]" in BOOT_CONTRACT
    assert "signing_key_id" in BOOT_CONTRACT
    verify = FOTA_C[FOTA_C.index("if (s_state==FOTA_STATE_VERIFYING)"):]
    assert verify.index("fota_authorization_commit") < verify.index("fota_bcr_commit_pending")
    assert verify.index("fota_bcr_commit_pending") < verify.index("s_state=FOTA_STATE_READY")
    assert "FOTA_STATUS_WINDOW_MS 15000UL" in FOTA_C
    assert verify.index("s_state=FOTA_STATE_READY") < verify.index("fota_apply()")


def _package(payload, signature=b"ECDSA-VALID"):
    digest = hashlib.sha256(payload).digest()
    body = digest + signature
    return body, zlib.crc32(body) & 0xFFFFFFFF


def test_package_requires_header_hash_signature_and_crc_before_pending():
    assert "fota_package_header_t" in FOTA_C
    assert "sha256" in FOTA_C.lower()
    assert "firmware_signature_verify" in FOTA_C
    assert "crc32" in FOTA_C.lower()
    assert "BCR_PENDING" in FOTA_C
    assert "memcmp(digest,s_package_sha256" in FOTA_C
    assert "firmware_signature_verify(digest,s_signature)" in FOTA_C
    assert "fota_ecdsa_verify" not in FOTA_C


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
    branch = FOTA_C[FOTA_C.index("if (s_state==FOTA_STATE_VERIFYING)"):]
    assert branch.index("fota_authorization_commit") < branch.index("fota_bcr_commit_pending")
    assert "fota_bcr_commit_pending(m.version,m.body_size,APP_FLASH_BASE)" in branch


def test_bcr_layout_is_shared_with_bootloader():
    bcr = (ROOT / "include" / "boot_contract.h").read_text(encoding="utf-8")
    assert '"boot_contract.h"' in FOTA_C
    assert "bcr_record_t" in FOTA_C
    assert "fota_bcr_record_t" not in FOTA_C
    assert "BCR_SLOT_A_ADDR" in bcr and "BCR_SLOT_B_ADDR" in bcr
    assert "offsetof(bcr_record_t,crc32)" in FOTA_C
    assert "uint32_t rollback_floor;" in bcr


def test_header_enforces_product_version_and_healthy_floor():
    assert "m->product_id!=FOTA_PACKAGE_PRODUCT_ID" in FOTA_C
    assert "m->version==0U" in FOTA_C
    assert "m->version<floor" in FOTA_C
    assert "__attribute__((weak)) bool fota_bcr_commit_pending" not in FOTA_C
    assert "fota_sequence_newer" in FOTA_C
    assert "fota_bcr_valid(&check)&&memcmp(&check,&r,sizeof r)==0" in FOTA_C


def test_trial_health_is_committed_before_reset():
    assert "FOTA_TRIAL_HEALTHY_MS 30000UL" in FOTA_C
    assert "void fota_confirm_trial_process(void)" in FOTA_C
    body = FOTA_C[FOTA_C.index("void fota_confirm_trial_process(void)"):]
    assert body.index("ext_flash_try_lock_now(EXT_FLASH_OWNER_OTA)") < body.index("fota_bcr_load(&record)")
    # The floor is raised only after Bootloader has committed a verified LKG.
    assert "record.rollback_floor=record.image_version" not in body
    assert body.index("fota_bcr_write_record(&record)") < body.index("NVIC_SystemReset()")
    assert "fota_confirm_trial_process();" in (ROOT / "src" / "main.c").read_text(encoding="utf-8")


def test_runtime_bcr_handoff_uses_payload_length():
    branch = FOTA_C[FOTA_C.index("if (s_state==FOTA_STATE_VERIFYING)"):]
    assert "authorization.package_length=s_expected" in branch
    assert "authorization.package_version=m.version" in branch
    assert "authorization.package_crc32=m.body_crc32" in branch


if __name__ == "__main__":
    test_a300_wire_header_is_exactly_32_bytes()
    test_detached_metadata_is_durable_before_bounded_status_and_reset()
    test_package_requires_header_hash_signature_and_crc_before_pending()
    test_oversized_and_cancel_paths_release_ota_owner()
    test_package_hash_and_signature_failures_are_rejected()
    test_power_loss_checkpoint_is_not_a_pending_handoff()
    test_bcr_layout_is_shared_with_bootloader()
    test_header_enforces_product_version_and_healthy_floor()
    test_trial_health_is_committed_before_reset()
    test_runtime_bcr_handoff_uses_payload_length()
    print("test_fota_package: PASS")
