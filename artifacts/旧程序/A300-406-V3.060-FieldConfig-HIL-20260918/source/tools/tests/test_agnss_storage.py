"""Host checks for dual-slot AGNSS commit semantics."""
import zlib

MARKER = 0xA66A55AA

def valid(m):
    return m.get("commit") == MARKER and m.get("length", 0) <= 0x40000 and m.get("crc") == zlib.crc32(m["data"]) & 0xffffffff

def newest(slots):
    good = [s for s in slots if valid(s)]
    return max(good, key=lambda s: s["sequence"]) if good else None

def test_torn_metadata_ignored():
    assert newest([{"sequence": 9, "length": 3, "data": b"abc", "crc": zlib.crc32(b"abc"), "commit": 0}]) is None

def test_newest_valid_slot_selected():
    a = {"sequence": 1, "length": 1, "data": b"a", "crc": zlib.crc32(b"a"), "commit": MARKER}
    b = {"sequence": 2, "length": 1, "data": b"b", "crc": zlib.crc32(b"b"), "commit": MARKER}
    assert newest([a, b]) is b

def test_empty_and_full_bounds():
    assert newest([]) is None
    assert valid({"sequence": 1, "length": 0x40000, "data": b"x" * 0x40000, "crc": zlib.crc32(b"x" * 0x40000), "commit": MARKER})

if __name__ == "__main__":
    test_torn_metadata_ignored(); test_newest_valid_slot_selected(); test_empty_and_full_bounds(); print("test_agnss_storage: PASS")
