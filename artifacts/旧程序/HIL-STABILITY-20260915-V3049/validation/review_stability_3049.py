"""Bounded local HIL delivery; original release gate remains authoritative."""
from pathlib import Path
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hil", ROOT / "build/build_hil_pair_20260913.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
h.WORK = ROOT / "build/stability-review-3049"
h.OUT = ROOT / "artifacts/HIL-STABILITY-20260915-V3049"
h.MAKE = ROOT.parent / "tools/w64devkit/w64devkit/bin/make.exe"
sys.path.insert(0, str(ROOT / "tools"))
import build_dev_release as builder


def tests():
    h.WORK.mkdir(exist_ok=False)
    names = sorted(set(
        [p.stem for p in (ROOT / "tools/tests").glob("test_fota_*.py")]
        + [p.stem for p in (ROOT / "tools/tests").glob("test_agnss_*.py")]
        + ["test_debug_uart_stats", "test_at_config_handoff", "test_heap_bounds", "test_ram_watermark", "test_stack_health_observability", "test_mileage_persistence", "test_build_dependencies", "test_build_version_refresh", "test_flash_capacity_guard", "test_flash_gate_build", "test_ram_guard", "test_lto_stack_guard", "test_f39_actions", "test_flash_config_migration", "test_hardware_bringup_profile", "test_sha256_shared", "test_cfg_query_lifetime", "test_cfg_query_contract",
           "test_ec800m_udp_async_contract", "test_service_workspace_contract",
           "test_jt808_dual_session", "test_jt808_session", "test_jt808_session_send_failure",
           "test_tcp_identity_gate", "test_tcp_manager_fip", "test_ec800m_urc_demux",
           "test_ec800m_dma_wrap", "test_debug_printf_format", "test_feature_guards",
           "test_ext_flash_store_host", "test_ext_flash_layout", "test_internal_flash_layout",
           "test_firmware_signature", "test_platform_trust_anchor", "test_boot_flash_probe_retry",
           "test_bootloader_factory_init", "test_bootloader_platform_contract",
           "test_bootloader_bcr_failclosed", "test_bootloader_lkg_powercut_c",
           "test_bootloader_invalid_vector_recovery", "test_boot_install_progress",
           "test_boot_progress_uart", "test_dev_release_manifest", "test_fota_package",
           "test_flash_combined_script", "test_blind_zone_store", "test_blind_zone_replay"]
    ))
    for name in names:
        h.run([sys.executable, f"tools/tests/{name}.py"], f"{name}.log")
    (h.WORK / "tests-passed.json").write_text(json.dumps(names, indent=2), encoding="utf-8")


def build():
    assert not h.OUT.exists(), "Never overwrite delivered firmware"
    assert (h.WORK / "tests-passed.json").exists()
    identity = h.set_version(49)
    h.run([sys.executable, "tools/tests/test_release_identity_contract.py"], "identity.log")
    app_rel = "build/stability-review-3049/app"
    h.run([h.MAKE, "-B", "-j4", "all", "BUILD=" + app_rel], "app-build.log")
    command = [str(h.MAKE), "release-gate", "BUILD=" + app_rel]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=180)
    output = result.stdout + result.stderr
    (h.WORK / "release-gate.log").write_text(output, encoding="utf-8")
    gate = {"command": command, "exit_code": result.returncode, "log": "release-gate.log"}
    (h.WORK / "release-gate-result.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")
    # HIL only, retaining the known incomplete-evidence rejection; other errors stop delivery.
    assert result.returncode != 0 and "release-guard: PASS" in output, output
    assert "RAM guard failed: stack evidence: incomplete stack evidence:" in output, output
    assert "stack-guard: INCOMPLETE" in output, output
    print("release gate: BLOCKED (incomplete stack evidence)", flush=True)
    h.run([sys.executable, "tools/tests/test_ram01_frame_budget.py", app_rel], "frame-budget.log")
    h.run([sys.executable, "tools/libc_parser_guard.py", app_rel + "/a300_firmware.map"], "libc.log")
    h.run([sys.executable, "tools/tests/test_platform_trust_anchor.py"], "final-trust.log")
    boot_rel = "../build/stability-review-3049/boot"
    mk = re.sub(r"\bbuild\b", boot_rel, (ROOT / "bootloader/Makefile").read_text(encoding="utf-8"))
    boot_mk = h.WORK / "boot-hil.mk"
    boot_mk.write_text(mk, encoding="utf-8")
    h.run([h.MAKE, "-f", boot_mk, "-B", "-j4", "all"], "boot-build.log", ROOT / "bootloader")
    boot_dir = h.WORK / "boot"
    h.run([sys.executable, "tools/map_ram_guard.py", "bootloader", boot_dir / "bootloader.map"], "boot-map.log")
    combined = builder.build_combined((boot_dir / "bootloader.bin").read_bytes(),
                                     (ROOT / app_rel / "a300_firmware.bin").read_bytes())
    h.OUT.mkdir()
    dest = h.package(identity, ROOT / app_rel, boot_dir)
    assert (dest / "Combined-N32L406CBL7.bin").read_bytes() == combined
    roundtrip = h.WORK / "hex-roundtrip.bin"
    h.run([h.TC / "arm-none-eabi-objcopy.exe", "-I", "ihex", "-O", "binary",
           dest / "Combined-N32L406CBL7.hex", roundtrip], "hex-roundtrip.log")
    assert roundtrip.read_bytes() == combined
    manifest = dest / "SHA256SUMS-N32L406CBL7.json"
    report = json.loads(manifest.read_text(encoding="utf-8"))
    report["release_gate"] = "failed: incomplete stack evidence; known-frame budget passed"
    report["factory_init"] = {"request_address": "0x08005800", "completion": "PENDING",
                              "hardware_validated": False, "applies_to": "Combined SWD only"}
    manifest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    h.run([sys.executable, "tools/tests/test_dev_release_manifest.py", "--manifest", manifest], "final-manifest.log")
    for folder in ["src", "include", "ldscript", "bootloader/src", "bootloader/include", "tools/tests"]:
        shutil.copytree(ROOT / folder, dest / "provenance" / folder, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
    for name in ["Makefile", "bootloader/Makefile", "tools/build_dev_release.py", "tools/gen_a300_ota_image.py"]:
        target = dest / "provenance" / name
        target.parent.mkdir(exist_ok=True, parents=True)
        shutil.copy2(ROOT / name, target)
    for source, target in [("Combined-N32L406CBL7.hex", "SWD-Combined-V3049.hex"),
                           ("Combined-N32L406CBL7.bin", "SWD-Combined-V3049.bin"),
                           ("App-N32L406CBL7.hex", "SWD-App-V3049.hex"),
                           ("A300-406-OTA-V3049.bin", "OTA-A300-406-V3049.bin")]:
        shutil.copy2(dest / source, h.OUT / target)
    shutil.copytree(h.WORK, h.OUT / "validation",
                    ignore=shutil.ignore_patterns("app", "boot", "*.bin"))
    shutil.copy2(__file__, h.OUT / "validation/review_stability_3049.py")
    shutil.copy2(ROOT / "build/build_hil_pair_20260913.py", h.OUT / "validation/build_hil_pair_20260913.py")
    print("PACKAGED", h.OUT, flush=True)


if __name__ == "__main__":
    {"tests": tests, "build": build}[sys.argv[1]]()
