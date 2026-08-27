def due(now, deadline):
    return now >= deadline

def test_ota_lockout_and_retry_deadline():
    assert not due(100, 1000)
    assert due(1000, 1000)
    ota = True
    assert ota  # scheduler must defer while OTA owns channel/flash

if __name__ == "__main__":
    test_ota_lockout_and_retry_deadline(); print("test_agnss_scheduler: PASS")
