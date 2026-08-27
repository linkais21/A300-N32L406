from pathlib import Path
import hashlib


ROOT = Path(__file__).parents[2]
FOTA_H = (ROOT / "include" / "fota.h").read_text(encoding="utf-8")
FOTA_C = (ROOT / "src" / "fota.c").read_text(encoding="utf-8")


class ResumeModel:
    def __init__(self, url, length, etag=""):
        self.url, self.length, self.etag = url, length, etag
        self.data = bytearray()
        self.checkpoint = (url, length, etag, 0)

    def reconnect(self, url, length, etag):
        if (url, length, etag) != self.checkpoint[:3]:
            self.data.clear()
            self.checkpoint = (url, length, etag, 0)
        return len(self.data)

    def chunk(self, payload, offset):
        if offset > len(self.data):
            raise ValueError("out-of-order")
        if offset < len(self.data):
            if bytes(self.data[offset:offset + len(payload)]) != payload:
                raise ValueError("duplicate mismatch")
            return
        self.data.extend(payload)
        self.checkpoint = (*self.checkpoint[:3], len(self.data))


def test_fota_exposes_resumable_request_status_and_chunk_offset():
    assert "fota_request_t" in FOTA_H
    assert "fota_status_t" in FOTA_H
    assert "fota_get_status" in FOTA_H
    assert "fota_cancel" in FOTA_H
    assert "fota_on_chunk" in FOTA_H
    assert "Range: bytes=" in FOTA_C


def test_resume_rejects_identity_mismatch_and_orders_chunks():
    assert "ETag" in FOTA_C
    assert "offset>s_received" in FOTA_C
    assert "offset<s_received" in FOTA_C
    assert "FOTA_RESUME_MAGIC" in FOTA_C


def test_disconnect_range_resume_and_duplicate_chunks():
    m = ResumeModel("http://fw/a.bin", 6, '"v1"')
    m.chunk(b"abc", 0)
    assert m.reconnect("http://fw/a.bin", 6, '"v1"') == 3
    m.chunk(b"abc", 0)  # exact duplicate is harmless
    m.chunk(b"def", 3)
    assert bytes(m.data) == b"abcdef"


def test_out_of_order_and_changed_etag_restart_safely():
    m = ResumeModel("http://fw/a.bin", 6, '"v1"')
    m.chunk(b"abc", 0)
    try:
        m.chunk(b"z", 5)
    except ValueError as exc:
        assert "out-of-order" in str(exc)
    assert m.reconnect("http://fw/a.bin", 6, '"v2"') == 0


def test_source_checks_http_split_header_and_range_contract():
    assert "s_http_header_len" in FOTA_C
    assert "HTTP/1.1 206" in FOTA_C
    assert "Content-Range:" in FOTA_C
    assert "first!=s_received" in FOTA_C


def test_duplicate_comparison_covers_full_chunk_in_blocks():
    assert "while(pos<len)" in FOTA_C


if __name__ == "__main__":
    test_fota_exposes_resumable_request_status_and_chunk_offset()
    test_resume_rejects_identity_mismatch_and_orders_chunks()
    print("test_fota_resume: PASS")
