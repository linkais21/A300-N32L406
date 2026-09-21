"""Exhaustive page-transaction power-cut tests for the bootloader model."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bootloader"))

from host_model import Bcr, BcrState, BcrStore, TransactionalInstaller
from host_model import TransactionalLkgStore


APP_MAX_SIZE = 0x1A000


def _operation_count(image_length):
    seed = TransactionalInstaller(bytes([0xAA]) * image_length, bytes([0x55]) * image_length)
    seed.seed_pending()
    seed.cut_at = None
    seed.op_index = 0
    seed.boot()
    assert bytes(seed.flash[:image_length]) == bytes([0x55]) * image_length
    assert seed.bcr.load().state == BcrState.TRIAL
    return seed.op_index


def _run_with_cut(image_length, cut_at):
    old = bytes([0xAA]) * image_length
    new = bytes([0x55]) * image_length
    bcr = BcrStore()
    seed = TransactionalInstaller(old, new, bcr=bcr)
    seed.seed_pending()
    run = TransactionalInstaller(old, new, cut_at=cut_at, bcr=bcr)
    # The internal Flash and BCR survive reset; the installer object does not.
    run.flash[:] = seed.flash
    run.boot()
    assert bytes(run.flash[:image_length]) == new
    assert run.bcr.load().state == BcrState.TRIAL
    assert run.bcr.load().offset == image_length
    assert run.jumps == ["trial"]


def test_every_page_operation_boundary_converges():
    """Every erase/program/readback/BCR boundary must be restartable."""
    for image_length in (2048, 2049, 4097):
        count = _operation_count(image_length)
        for cut_at in range(1, count + 1):
            _run_with_cut(image_length, cut_at)


def test_max_image_and_final_partial_page():
    image_length = APP_MAX_SIZE
    count = _operation_count(image_length)
    # Exhaustively exercise the maximum image too. This includes its exact
    # final page boundary; 2049 above covers a non-full final page.
    for cut_at in range(1, count + 1):
        _run_with_cut(image_length, cut_at)


def test_pending_never_jumps_and_offset_is_boundary_or_final_length():
    image_length = 2049
    old = bytes([0xAA]) * image_length
    new = bytes([0x55]) * image_length
    bcr = BcrStore()
    seed = TransactionalInstaller(old, new, bcr=bcr)
    seed.seed_pending()
    run = TransactionalInstaller(old, new, cut_at=3, bcr=bcr)
    run.flash[:] = seed.flash
    try:
        run.resume()
    except RuntimeError:
        pass
    record = bcr.load()
    assert record.state == BcrState.PENDING
    assert record.offset in (0, 2048, image_length)
    assert run.jumps == []


def test_bcr_sequence_wrap_selects_newer_slot():
    store = BcrStore()
    store.slots = [Bcr(sequence=0xFFFFFFFF, state=BcrState.PENDING),
                   Bcr(sequence=0, state=BcrState.PENDING)]
    assert store.load().sequence == 0


def test_installer_skips_a300_package_header():
    body = bytes(range(64))
    package = bytes([0xCC]) * 32 + body
    installer = TransactionalInstaller(bytes([0xAA]) * len(body), package)
    installer.seed_pending()
    installer.boot()
    assert bytes(installer.flash[:len(body)]) == body


def test_every_lkg_promotion_cut_retains_a_valid_slot():
    package = bytes(range(251)) * 500
    baseline = TransactionalLkgStore(b"old-lkg", generation=7)
    operations = baseline.operation_count(package)
    for cut_at in range(1, operations + 1):
        store = TransactionalLkgStore(b"old-lkg", generation=7)
        store.promote_with_resets(package, cut_at)
        assert store.read_newest() in (b"old-lkg", package)
        store.promote_with_resets(package, None)
        assert store.read_newest() == package


if __name__ == "__main__":
    test_every_page_operation_boundary_converges()
    test_max_image_and_final_partial_page()
    test_pending_never_jumps_and_offset_is_boundary_or_final_length()
    test_installer_skips_a300_package_header()
    test_every_lkg_promotion_cut_retains_a_valid_slot()
    print("test_bootloader_powercut: PASS")
