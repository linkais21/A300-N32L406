import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[2]
layout = (ROOT / "include" / "ext_flash_layout.h").read_text(encoding="utf-8")

def val(name):
    m = re.search(rf"#define\s+{name}\s+([^\n]+)", layout)
    assert m, name
    expr = m.group(1).split("/*")[0].strip().replace("UL", "").replace("U", "").replace("/", "//")
    env = {"FLASH_TOTAL_SIZE": 2 * 1024 * 1024, "FLASH_SECTOR_SIZE": 4096}
    for dep in set(re.findall(r"EXT_FLASH_[A-Z0-9_]+", expr)):
        if dep != name:
            env[dep] = val(dep)
    return eval(expr, {"__builtins__": {}}, env)

def test_regions_non_overlapping_and_in_bounds():
    regs = [("candidate", val("EXT_FLASH_CANDIDATE_ADDR"), val("EXT_FLASH_CANDIDATE_SIZE")),
            ("factory", val("EXT_FLASH_FACTORY_ADDR"), val("EXT_FLASH_FACTORY_SIZE")),
            ("lkg", val("EXT_FLASH_LKG_ADDR"), val("EXT_FLASH_LKG_SIZE")),
            ("resume", val("EXT_FLASH_RESUME_ADDR"), val("EXT_FLASH_RESUME_SIZE")),
            ("blind", val("EXT_FLASH_BLIND_ADDR"), val("EXT_FLASH_BLIND_SIZE")),
            ("agnss", val("EXT_FLASH_AGNSS_ADDR"), val("EXT_FLASH_AGNSS_SIZE"))]
    for i, (_, addr, size) in enumerate(regs):
        assert addr + size <= 2 * 1024 * 1024
        if i:
            assert regs[i - 1][1] + regs[i - 1][2] <= addr

def test_page_split_formula():
    addr, length = 0x1F0, 32
    assert min(256 - (addr % 256), length) == 16

def test_timeout_and_owner_contracts_present():
    spi = (ROOT / "src" / "spi_flash.c").read_text()
    store = (ROOT / "src" / "ext_flash_store.c").read_text()
    assert "SPI_FLASH_TIMEOUT_MS" in spi and "ready" in spi
    assert "return false" in spi
    assert "ext_flash_try_lock" in store and "EXT_FLASH_OWNER_NONE" in store
    assert "FLASH_SECTOR_SIZE" in store
    assert "SPI_FLASH_ERASE_TIMEOUT_MS" in (ROOT / "include" / "spi_flash.h").read_text(encoding="utf-8")
    assert "0x684015" in spi
    assert "FOTA_MAX_SIZE     EXT_FLASH_CANDIDATE_SIZE" in (ROOT / "include" / "fota.h").read_text(encoding="utf-8")
    assert "FOTA_PENDING_ADDR EXT_FLASH_RESUME_ADDR" in (ROOT / "include" / "fota.h").read_text(encoding="utf-8")

def test_config_layout_and_owner_enforcement():
    layout_h = (ROOT / "include" / "ext_flash_layout.h").read_text(encoding="utf-8")
    cfg_h = (ROOT / "include" / "flash_config.h").read_text(encoding="utf-8")
    store_h = (ROOT / "include" / "ext_flash_store.h").read_text(encoding="utf-8")
    store_c = (ROOT / "src" / "ext_flash_store.c").read_text(encoding="utf-8")
    assert "EXT_FLASH_CONFIG_SLOT_A_ADDR" in layout_h and "EXT_FLASH_CONFIG_SLOT_B_ADDR" in layout_h
    assert "CFG_FLASH_ADDR_A    EXT_FLASH_CONFIG_SLOT_A_ADDR" in cfg_h
    assert "ext_flash_read(ext_flash_owner_t owner" in store_h
    assert "owner_ok(owner)" in store_c

def test_agnss_alignment_and_exact_slots():
    assert val("EXT_FLASH_AGNSS_META_SIZE") % 4096 == 0
    assert val("EXT_FLASH_AGNSS_SLOT_SIZE") % 4096 == 0
    tail_addr = val("EXT_FLASH_AGNSS_RESERVED_TAIL_ADDR")
    tail_size = val("EXT_FLASH_AGNSS_RESERVED_TAIL_SIZE")
    assert tail_size == 4096
    assert tail_addr % 4096 == 0
    assert val("EXT_FLASH_AGNSS_SLOT_B_ADDR") + val("EXT_FLASH_AGNSS_SLOT_SIZE") <= tail_addr
    assert tail_addr + tail_size == val("EXT_FLASH_AGNSS_ADDR") + val("EXT_FLASH_AGNSS_SIZE")
    assert tail_addr + tail_size <= 2 * 1024 * 1024

def test_layout_header_preprocesses_and_compiles():
    gcc = shutil.which("gcc")
    assert gcc, "gcc is required for the layout header compile check"
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "layout_check.c"
        obj = Path(td) / "layout_check.o"
        src.write_text(
            '#include "ext_flash_layout.h"\n'
            'int layout_check(void) {\n'
            '    return (int)(EXT_FLASH_AGNSS_RESERVED_TAIL_ADDR + EXT_FLASH_AGNSS_RESERVED_TAIL_SIZE);\n'
            '}\n',
            encoding="utf-8",
        )
        result = subprocess.run(
            [gcc, "-std=c11", "-Wall", "-Werror", "-I", str(ROOT / "include"), "-c", str(src), "-o", str(obj)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

if __name__ == "__main__":
    test_regions_non_overlapping_and_in_bounds()
    test_page_split_formula()
    test_timeout_and_owner_contracts_present()
    test_config_layout_and_owner_enforcement()
    test_agnss_alignment_and_exact_slots()
    print("test_ext_flash_layout: PASS")
