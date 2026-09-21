#!/usr/bin/env python3
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include "overspeed_policy.h"

int main(void)
{
    overspeed_policy_t policy;

    overspeed_policy_init(&policy);
    assert(!overspeed_policy_step(&policy, 0U, true, true, 120.0f, 120U));
    assert(!overspeed_policy_step(&policy, 1U, true, true, 120.1f, 120U));
    assert(!overspeed_policy_step(&policy, 10000U, true, true, 120.1f, 120U));
    assert(overspeed_policy_step(&policy, 10001U, true, true, 120.1f, 120U));
    assert(!overspeed_policy_step(&policy, 600000U, true, true, 180.0f, 120U));

    assert(!overspeed_policy_step(&policy, 601000U, true, true, 100.0f, 120U));
    assert(!overspeed_policy_step(&policy, 602000U, true, true, 130.0f, 120U));
    assert(overspeed_policy_step(&policy, 612000U, true, true, 130.0f, 120U));

    assert(!overspeed_policy_step(&policy, 613000U, true, true, 100.0f, 120U));
    assert(!overspeed_policy_step(&policy, 614000U, false, true, 180.0f, 120U));
    assert(!overspeed_policy_step(&policy, 624000U, true, true, 180.0f, 120U));
    assert(!overspeed_policy_step(&policy, 634000U, true, true, 180.0f, 120U));
    assert(overspeed_policy_step(&policy, 912000U, true, true, 180.0f, 120U));

    overspeed_policy_init(&policy);
    assert(!overspeed_policy_step(&policy, UINT32_MAX - 5000U, true, true, 121.0f, 120U));
    assert(overspeed_policy_step(&policy, 4999U, true, true, 121.0f, 120U));

    overspeed_policy_init(&policy);
    assert(!overspeed_policy_step(&policy, 0U, true, false, 150.0f, 120U));
    assert(!overspeed_policy_step(&policy, 10000U, true, true, 150.0f, 0U));
    return 0;
}
'''


def compiler():
    return os.environ.get("CC") or shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")


def main():
    main_source = (ROOT / "src" / "main.c").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    required = (
        "overspeed_policy_step(",
        "cfg_get()->speed_limit_kmh",
        "jt808_trigger_alarm(ALM_OVERSPEED)",
        "work_mode_notify_alarm(ALM_OVERSPEED)",
    )
    for marker in required:
        if marker not in main_source:
            print(f"test_overspeed_policy: FAIL (missing main wiring: {marker})")
            return 1
    if "src/overspeed_policy.c" not in makefile:
        print("test_overspeed_policy: FAIL (overspeed_policy.c not in Makefile)")
        return 1
    cc = compiler()
    if not cc:
        print("test_overspeed_policy: FAIL (host compiler required)")
        return 1
    with tempfile.TemporaryDirectory(prefix="overspeed_policy_") as directory:
        temp = Path(directory)
        source = temp / "h.c"
        executable = temp / "h.exe"
        source.write_text(HARNESS, encoding="ascii")
        command = [cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
                   "-I", str(ROOT / "include"), str(source),
                   str(ROOT / "src" / "overspeed_policy.c"),
                   "-o", str(executable)]
        built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if built.returncode:
            print(built.stdout + built.stderr, end="")
            return built.returncode
        run = subprocess.run([str(executable)], cwd=ROOT, capture_output=True, text=True)
        if run.returncode:
            print(run.stdout + run.stderr, end="")
            return run.returncode
    print("test_overspeed_policy: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
