from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def run():
    header = ROOT / "include" / "service_workspace.h"
    source = ROOT / "src" / "service_workspace.c"
    assert header.exists(), "service workspace header is missing"
    assert source.exists(), "service workspace implementation is missing"
    text = header.read_text(encoding="ascii")
    impl = source.read_text(encoding="ascii")
    for token in ("service_workspace_try_acquire", "service_workspace_release",
                  "service_workspace_buffer"):
        assert token in text and token in impl, token
    assert "SERVICE_WORKSPACE_OWNER_OTA" in text
    assert "SERVICE_WORKSPACE_OWNER_DIAGNOSTIC" in text
    assert "static uint8_t" in impl
    assert "SERVICE_WORKSPACE_CAPACITY" in impl
    ec = (ROOT / "src" / "ec800m.c").read_text(encoding="utf-8", errors="ignore")
    assert "s_line_buf" in ec and "s_at_resp" in ec
    # The safety-critical UART/DMA receive buffers remain owned by EC800M.
    assert "service_workspace_buffer" not in ec
    fota = (ROOT / "src" / "fota.c").read_text(encoding="utf-8", errors="ignore")
    assert "service_workspace_try_acquire" in fota
    assert "service_workspace_buffer" in fota
    assert "s_http_header[512]" not in fota

    harness = r'''
#include "service_workspace.h"
#include <assert.h>
#include <stddef.h>
int main(void) {
    size_t n = 0;
    assert(service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_OTA));
    assert(!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_DIAGNOSTIC));
    assert(service_workspace_buffer(&n) != 0 && n >= 512);
    service_workspace_release(SERVICE_WORKSPACE_OWNER_DIAGNOSTIC);
    assert(service_workspace_buffer(&n) != 0);
    service_workspace_release(SERVICE_WORKSPACE_OWNER_OTA);
    assert(service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_DIAGNOSTIC));
    service_workspace_release(SERVICE_WORKSPACE_OWNER_DIAGNOSTIC);
    return 0;
}
'''
    with tempfile.TemporaryDirectory() as td:
        c = Path(td) / "harness.c"
        exe = Path(td) / "harness.exe"
        c.write_text(harness, encoding="ascii")
        result = subprocess.run(["gcc", "-std=c99", "-I", str(ROOT / "include"),
                                 str(c), str(source), "-o", str(exe)], cwd=ROOT)
        assert result.returncode == 0, "workspace harness did not compile"
        result = subprocess.run([str(exe)], cwd=ROOT)
        assert result.returncode == 0, "workspace owner exclusion failed"
    print("service workspace contract: PASS")


if __name__ == "__main__":
    run()
