from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_reset_capture_precedes_hardware_init_and_clears_flags():
    source = (ROOT / "src" / "reset_diag.c").read_text(encoding="utf-8")
    main = (ROOT / "src" / "main.c").read_text(encoding="utf-8")
    for flag in ("IWDGRSTF", "WWDGRSTF", "SFTRSTF", "PINRSTF", "PORRSTF", "LPWRRSTF"):
        assert flag in source
    assert "RCC_ClrFlag();" in source
    assert main.index("reset_diag_capture();") < main.index("hw_clock_init();")


if __name__ == "__main__":
    test_reset_capture_precedes_hardware_init_and_clears_flags()
    print("test_reset_diag: PASS")
