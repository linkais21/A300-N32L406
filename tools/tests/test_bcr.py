import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "bootloader"))

from host_model import Bcr, BcrState, BcrStore, select_recovery_image


def test_torn_record_keeps_previous_slot():
    store = BcrStore()
    first = Bcr(sequence=1, state=BcrState.ACTIVE, version=10)
    store.commit(first)
    store.torn_next_write = True
    store.commit(Bcr(sequence=2, state=BcrState.TRIAL, version=11))
    assert store.load() == first


def test_three_trial_failures_roll_back_lkg_then_factory_then_recovery():
    assert select_recovery_image(BcrState.TRIAL, 3, True, True) == "lkg"
    assert select_recovery_image(BcrState.TRIAL, 3, False, True) == "factory"
    assert select_recovery_image(BcrState.TRIAL, 3, False, False) == "recovery"
    assert select_recovery_image(BcrState.ROLLBACK, 3, True, True) == "lkg"


if __name__ == "__main__":
    test_torn_record_keeps_previous_slot()
    test_three_trial_failures_roll_back_lkg_then_factory_then_recovery()
    print("test_bcr: PASS")
