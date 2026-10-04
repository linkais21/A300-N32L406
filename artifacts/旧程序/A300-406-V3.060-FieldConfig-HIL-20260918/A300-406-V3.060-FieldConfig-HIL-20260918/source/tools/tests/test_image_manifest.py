import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "bootloader"))

from host_model import ImageManifest, ManifestError


def test_manifest_rejects_bad_signature_and_downgrade():
    m = ImageManifest.build(b"application", version=12, product=0x41333030, hardware=0x343036)
    assert m.verify(b"application", current_version=11, product=0x41333030, hardware=0x343036)
    m.signature = b"bad"
    try:
        m.verify(b"application", current_version=11, product=0x41333030, hardware=0x343036)
    except ManifestError as exc:
        assert "signature" in str(exc)
    else:
        raise AssertionError("bad signature accepted")

    m = ImageManifest.build(b"application", version=10, product=0x41333030, hardware=0x343036)
    try:
        m.verify(b"application", current_version=11, product=0x41333030, hardware=0x343036)
    except ManifestError as exc:
        assert "downgrade" in str(exc)
    else:
        raise AssertionError("downgrade accepted")


def test_manifest_detects_payload_corruption():
    m = ImageManifest.build(b"application", version=12, product=1, hardware=2)
    try:
        m.verify(b"corrupt", current_version=0, product=1, hardware=2)
    except ManifestError as exc:
        assert "sha" in str(exc)
    else:
        raise AssertionError("corrupt image accepted")



if __name__ == "__main__":
    test_manifest_rejects_bad_signature_and_downgrade()
    test_manifest_detects_payload_corruption()
    print("test_image_manifest: PASS")
