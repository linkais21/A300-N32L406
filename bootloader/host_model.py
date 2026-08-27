"""Deterministic host model for bootloader transaction tests."""
from dataclasses import dataclass
from enum import IntEnum
import hashlib
import zlib


class BcrState(IntEnum):
    ACTIVE = 1
    TRIAL = 2
    PENDING = 3
    ROLLBACK = 4
    RECOVERY = 5


@dataclass(eq=True)
class Bcr:
    sequence: int
    state: BcrState
    version: int = 0
    attempts: int = 0
    offset: int = 0


class BcrStore:
    def __init__(self):
        self.slots = [None, None]
        self.active_slot = 0
        self.torn_next_write = False

    def commit(self, record):
        if self.torn_next_write:
            self.torn_next_write = False
            return
        slot = 1 - self.active_slot
        self.slots[slot] = record
        self.active_slot = slot

    def load(self):
        valid = [r for r in self.slots if r is not None]
        return max(valid, key=lambda r: r.sequence) if valid else None


def select_recovery_image(state, attempts, lkg_valid, factory_valid):
    if state in (BcrState.TRIAL, BcrState.ROLLBACK) and attempts >= 3:
        if lkg_valid:
            return "lkg"
        if factory_valid:
            return "factory"
        return "recovery"
    return "candidate" if state in (BcrState.PENDING, BcrState.TRIAL) else "active"


class ManifestError(ValueError):
    pass


@dataclass
class ImageManifest:
    payload_hash: bytes
    signature: bytes
    version: int
    product: int
    hardware: int
    crc32: int

    @classmethod
    def build(cls, payload, version, product, hardware):
        digest = hashlib.sha256(payload).digest()
        # The production verifier delegates ECDSA to a platform callback.  The
        # host model uses a deterministic signature marker for protocol tests.
        signature = b"ECDSA-VALID" + digest[:8]
        body = digest + signature + version.to_bytes(4, "little") + product.to_bytes(4, "little") + hardware.to_bytes(4, "little")
        return cls(digest, signature, version, product, hardware, zlib.crc32(body) & 0xffffffff)

    def verify(self, payload, current_version, product, hardware):
        if self.product != product or self.hardware != hardware:
            raise ManifestError("product/hardware mismatch")
        if self.version < current_version:
            raise ManifestError("downgrade rejected")
        if hashlib.sha256(payload).digest() != self.payload_hash:
            raise ManifestError("sha mismatch")
        if not self.signature.startswith(b"ECDSA-VALID"):
            raise ManifestError("signature rejected")
        body = self.payload_hash + self.signature + self.version.to_bytes(4, "little") + self.product.to_bytes(4, "little") + self.hardware.to_bytes(4, "little")
        if zlib.crc32(body) & 0xffffffff != self.crc32:
            raise ManifestError("manifest crc mismatch")
        return True
