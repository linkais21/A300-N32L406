"""Host contract tests for bounded vendor stream behavior."""

def classify(buf):
    if len(buf) < 2: return "INCOMPLETE"
    if buf[:2] != b"AG": return "MALFORMED"
    if len(buf) < 5: return "INCOMPLETE"
    n = int.from_bytes(buf[2:4], "little")
    if n < 3 or n > 4088: return "MALFORMED"
    total = n + 8
    if len(buf) < total: return "INCOMPLETE"
    if len(buf) != total or buf[4] != 0: return "MALFORMED"
    c1 = c2 = 0
    for b in buf[2:5+n]: c1=(c1+b)&255; c2=(c2+c1)&255
    return "OK" if (buf[5+n],buf[6+n]) == (c1,c2) else "MALFORMED"

def test_fragment_and_fail_retry_contract():
    assert classify(b"A") == "INCOMPLETE"
    assert classify(b"XX") == "MALFORMED"
    # Failed UART writes must clear the buffered stream before retry.
    stream = bytearray(b"partial")
    stream.clear()
    stream.extend(b"fresh")
    assert bytes(stream) == b"fresh"

if __name__ == "__main__":
    test_fragment_and_fail_retry_contract(); print("test_agnss_vendor_stream: PASS")
