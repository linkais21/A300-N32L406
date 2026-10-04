"""Deterministic host model for bootloader transaction tests."""
from dataclasses import dataclass
from enum import IntEnum
import hashlib
import zlib


class PowerCut(RuntimeError):
    """A reset at one persistent operation boundary."""


class TransactionalInstaller:
    """Small NOR/BCR model used by the power-cut tests.

    The model deliberately exposes the physical operation boundaries: an
    internal page erase, each 256-byte program and immediate readback, the
    page readback pass, and each BCR dual-slot commit operation.
    """

    PAGE_SIZE = 2048
    CHUNK_SIZE = 256
    BCR_PENDING = 3
    BCR_TRIAL = 2

    def __init__(self, old_image, candidate, cut_at=None, bcr=None, cut_budget=3):
        flash_size = ((len(old_image) + self.PAGE_SIZE - 1) // self.PAGE_SIZE) * self.PAGE_SIZE
        self.flash = bytearray(old_image) + bytearray([0xAA]) * (flash_size - len(old_image))
        raw = bytes(candidate)
        self.candidate = raw[32:] if len(raw) >= 32 and raw[:32] == bytes([0xCC]) * 32 else raw
        self.cut_at = cut_at
        self.cut_name = None
        self.cut_budget = cut_budget
        self.resets = 0
        self.op_index = 0
        self.bcr = bcr if bcr is not None else BcrStore()
        self.jumps = []

    def _op(self, name):
        self.op_index += 1
        if self.cut_at == self.op_index:
            self.cut_name = name
        if self.cut_name == name and self.cut_budget:
            self.cut_budget -= 1
            self.resets += 1
            raise PowerCut(name)

    def _erase_page(self, start):
        self._op(f"page-erase-before:{start}")
        self.flash[start:start + self.PAGE_SIZE] = b"\xff" * self.PAGE_SIZE
        self._op(f"page-erase-after:{start}")

    def _program(self, start, data):
        self._op(f"program-256-before:{start}")
        for index, value in enumerate(data):
            previous = self.flash[start + index]
            if value | previous != previous:
                raise AssertionError("NOR 0-to-1 program")
            self.flash[start + index] = previous & value
        self._op(f"program-256-after:{start}")
        self._op(f"chunk-readback-before:{start}")
        assert bytes(self.flash[start:start + len(data)]) == data
        self._op(f"chunk-readback-after:{start}")

    def _page_readback(self, start, data):
        for offset in range(0, len(data), self.CHUNK_SIZE):
            size = min(self.CHUNK_SIZE, len(data) - offset)
            self._op(f"page-readback-before:{start + offset}")
            assert bytes(self.flash[start + offset:start + offset + size]) == data[offset:offset + size]
            self._op(f"page-readback-after:{start + offset}")

    def _commit(self, offset, state=BCR_PENDING):
        record = Bcr(sequence=((self.bcr.load().sequence + 1) & 0xFFFFFFFF if self.bcr.load() else 1),
                     state=state, offset=offset)
        self.bcr.commit(record, operation=lambda name: self._op(f"{name}:{offset}:{int(state)}"))

    def seed_pending(self):
        self._commit(0)

    def resume(self):
        record = self.bcr.load()
        assert record is not None
        if record.state != BcrState.PENDING:
            return
        offset = record.offset
        assert offset == 0 or offset % self.PAGE_SIZE == 0 or offset == len(self.candidate)
        if offset == len(self.candidate):
            self._commit(offset, BcrState.TRIAL)
            return
        page_size = min(self.PAGE_SIZE, len(self.candidate) - offset)
        self._erase_page(offset)
        page = self.candidate[offset:offset + page_size]
        for position in range(0, page_size, self.CHUNK_SIZE):
            size = min(self.CHUNK_SIZE, page_size - position)
            self._program(offset + position, page[position:position + size])
        self._page_readback(offset, page)
        self._commit(offset + page_size)

    def boot(self):
        """Reboot/resume until the pending transaction converges."""
        while True:
            try:
                self.resume()
                if self.bcr.load().state == BcrState.TRIAL:
                    self.jumps.append("trial")
                    return
            except PowerCut:
                if self.bcr.load().state == BcrState.TRIAL:
                    self.jumps.append("trial")
                    return
                assert self.bcr.load().state == BcrState.PENDING
                continue


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
    marker: bool = True


class BcrStore:
    def __init__(self):
        self.slots = [None, None]
        self.active_slot = 0
        self.torn_next_write = False

    def commit(self, record, operation=None):
        if self.torn_next_write:
            self.torn_next_write = False
            return
        if operation is not None:
            operation("bcr-erase-before")
        selected = self.load()
        if selected is None:
            slot = 0
        else:
            selected_index = next(index for index, value in enumerate(self.slots)
                                  if value is selected)
            slot = 1 - selected_index
        self.slots[slot] = None
        if operation is not None:
            operation("bcr-erase-after")
            operation("bcr-body-before")
        body = Bcr(record.sequence, record.state, record.version, record.attempts,
                   record.offset, marker=False)
        self.slots[slot] = body
        if operation is not None:
            operation("bcr-body-after")
            operation("bcr-marker-before")
        self.slots[slot] = Bcr(record.sequence, record.state, record.version,
                               record.attempts, record.offset, marker=True)
        self.active_slot = slot
        if operation is not None:
            operation("bcr-marker-after")
            operation("bcr-body-readback-before")
            operation("bcr-body-readback-after")
            operation("bcr-marker-readback-before")
            operation("bcr-marker-readback-after")

    def load(self):
        valid = [r for r in self.slots if r is not None and r.marker]
        if not valid:
            return None
        if len(valid) == 1:
            return valid[0]
        first, second = valid[0], valid[1]
        newer = ((first.sequence - second.sequence) & 0xFFFFFFFF) != 0 and \
                ((first.sequence - second.sequence) & 0xFFFFFFFF) < 0x80000000
        return first if newer else second


class TransactionalLkgStore:
    """Two-slot package/auth commit model used to exhaust promotion cuts."""
    CHUNK = 256

    def __init__(self, initial, generation=1):
        self.slots = [{"package": bytes(initial), "generation": generation,
                       "committed": True}, None]
        self.op = 0

    def read_newest(self):
        valid = [slot for slot in self.slots if slot and slot["committed"]]
        if not valid:
            return None
        return max(valid, key=lambda slot: slot["generation"])["package"]

    def _promote(self, package, cut_at):
        valid = [(index, slot) for index, slot in enumerate(self.slots)
                 if slot and slot["committed"]]
        newest = max(valid, key=lambda item: item[1]["generation"]) if valid else None
        target = 1 - newest[0] if newest else 1
        generation = newest[1]["generation"] + 1 if newest else 1

        def step():
            self.op += 1
            if cut_at == self.op:
                raise PowerCut("lkg-promotion")

        step()
        self.slots[target] = None
        staged = bytearray()
        for offset in range(0, len(package), self.CHUNK):
            chunk = package[offset:offset + self.CHUNK]
            step()
            staged.extend(chunk)
            step()
            assert bytes(staged[-len(chunk):]) == chunk
        step()
        self.slots[target] = {"package": bytes(staged), "generation": generation,
                              "committed": False}
        step()
        self.slots[target]["committed"] = True
        step()
        assert self.slots[target]["package"] == package

    def operation_count(self, package):
        clone = TransactionalLkgStore(self.read_newest(),
                                      max(s["generation"] for s in self.slots if s))
        clone._promote(package, None)
        return clone.op

    def promote_with_resets(self, package, cut_at):
        self.op = 0
        try:
            self._promote(package, cut_at)
        except PowerCut:
            pass


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
