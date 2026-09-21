"""User-requested HIL files; preserve incomplete release gate, never approve release."""
from pathlib import Path
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hil', ROOT/'build/build_hil_pair_20260913.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
h.OUT = ROOT/'artifacts/HIL-OTA-PROGRESS-20260914-V3047'
h.WORK = ROOT/'build/hil-ota-progress-3047'
h.MAKE = Path('D:/A300_Tools/toolchains/make-4.4.1/bin/make.exe')
assert (not h.OUT.exists() or not any(h.OUT.iterdir())) and not h.WORK.exists(), 'never overwrite previous outputs'
h.WORK.mkdir()
h.OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT/'tools'))
import build_dev_release as builder

for name in ['test_platform_trust_anchor', 'test_boot_flash_probe_retry',
             'test_bootloader_factory_init', 'test_bootloader_platform_contract',
             'test_bootloader_bcr_failclosed', 'test_ext_flash_layout',
             'test_internal_flash_layout', 'test_dev_release_manifest',
             'test_fota_package', 'test_fota_platform_flow', 'test_fota_checkpoint_powercut',
             'test_fota_modem_handoff', 'test_gps_drop_diagnostics', 'test_nmea_replay',
             'test_at_config_serial_f39', 'test_flash_combined_script',
             'test_boot_install_progress', 'test_boot_progress_uart', 'test_fota_progress_display',
             'test_fota_resume', 'test_bootloader_lkg_powercut_c', 'test_bootloader_invalid_vector_recovery']:
    h.run([sys.executable, 'tools/tests/'+name+'.py'], name+'.log')

# Build boot in an isolated output tree with the existing relocation mechanism.
boot_rel = '../build/hil-ota-progress-3047/boot'
mk = re.sub(r'\bbuild\b', boot_rel, (ROOT/'bootloader/Makefile').read_text(encoding='utf-8'))
boot_mk = h.WORK/'boot-hil.mk'
boot_mk.write_text(mk, encoding='utf-8')
h.run([h.MAKE, '-f', boot_mk, '-B', '-j4', 'all', 'TOOLCHAIN_ROOT='+h.TC.as_posix()],
      'boot-build.log', ROOT/'bootloader')
boot_dir = h.WORK/'boot'
h.run([sys.executable, 'tools/map_ram_guard.py', 'bootloader', boot_dir/'bootloader.map'], 'boot-map.log')
boot = (boot_dir/'bootloader.bin').read_bytes()
builder.validate_factory_init_marker(boot)
sections = h.run([h.TC/'arm-none-eabi-objdump.exe', '-h', boot_dir/'bootloader.elf'], 'boot-sections.log')
assert '.factory_init_request 0000001c  08005800' in sections

for rev in [47]:
    ident = h.set_version(rev)
    counter = 3000+rev
    build = f'build/hil-ota-progress-3047/V{counter}'
    h.run([sys.executable, 'tools/tests/test_release_identity_contract.py'], f'V{counter}-identity.log')
    h.run([h.MAKE, '-B', '-j4', 'all', 'BUILD='+build, 'TOOLCHAIN_DIR='+h.TC.as_posix()], f'V{counter}-build.log')
    # Unlike the old HIL pair, known frames now fit; incomplete evidence still blocks.
    cmd = [str(h.MAKE), 'release-gate', 'BUILD='+build, 'TOOLCHAIN_DIR='+h.TC.as_posix()]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    output = result.stdout+result.stderr
    log = f'V{counter}-release-gate.log'
    (h.WORK/log).write_text(output, encoding='utf-8')
    h.COMMANDS.append({'command':cmd, 'exit_code':result.returncode, 'log':log})
    assert result.returncode != 0 and 'release-guard: PASS' in output
    assert 'RAM guard failed: stack evidence: incomplete stack evidence:' in output, output
    assert 'stack-guard: INCOMPLETE' in output
    print(log, 'EXPECTED INCOMPLETE RAM BLOCK', flush=True)
    h.run([sys.executable, 'tools/tests/test_ram01_frame_budget.py', build], f'V{counter}-frame-budget.log')
    h.run([sys.executable, 'tools/libc_parser_guard.py', build+'/a300_firmware.map'], f'V{counter}-libc.log')
    combined = builder.build_combined(boot, (ROOT/build/'a300_firmware.bin').read_bytes())
    dest = h.package(ident, ROOT/build, boot_dir)
    assert (dest/'Combined-N32L406CBL7.bin').read_bytes() == combined
    # Validate HEX roundtrip independently, including factory marker and App boundary.
    roundtrip = h.WORK/f'V{counter}-roundtrip.bin'
    h.run([h.TC/'arm-none-eabi-objcopy.exe', '-I', 'ihex', '-O', 'binary',
           dest/'Combined-N32L406CBL7.hex', roundtrip], f'V{counter}-hex-check.log')
    assert roundtrip.read_bytes() == combined
    manifest = dest/'SHA256SUMS-N32L406CBL7.json'
    report = json.loads(manifest.read_text(encoding='utf-8'))
    report['release_gate'] = 'failed: incomplete stack evidence; necessary known-frame budget passed'
    report['factory_init'] = {'request_address':'0x08005800', 'completion':'PENDING',
                              'hardware_validated':False, 'applies_to':'Combined SWD only; OTA is App-only'}
    manifest.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    for name in ['src/at_config.c','src/fota.c','src/gps.c','src/main.c','include/gps.h',
                 'bootloader/src/platform_n32l406.c','bootloader/src/factory_init.c',
                 'bootloader/src/boot_progress.c','bootloader/src/image_install.c',
                 'bootloader/include/image_install.h','bootloader/Makefile',
                 'tools/tests/test_boot_install_progress.py','tools/tests/test_boot_progress_uart.py',
                 'tools/tests/test_fota_progress_display.py',
                 'tools/tests/test_gps_drop_diagnostics.py','tools/tests/test_ram01_frame_budget.py']:
        target=dest/'provenance'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/name,target)
    h.run([sys.executable, 'tools/tests/test_dev_release_manifest.py', '--manifest', manifest], f'V{counter}-final-manifest.log')

for src, target in [('V3.047/Combined-N32L406CBL7.hex','SWD-Combined-V3047.hex'),
                    ('V3.047/Combined-N32L406CBL7.bin','SWD-Combined-V3047.bin'),
                    ('V3.047/A300-406-OTA-V3047.bin','OTA-A300-406-V3047.bin')]:
    shutil.copy2(h.OUT/src,h.OUT/target)
shutil.copytree(h.WORK,h.OUT/'validation',ignore=shutil.ignore_patterns('boot','V3047','*.bin'))
shutil.copy2(__file__,h.OUT/'validation/build_ota_progress_3047.py')
print('PACKAGED', h.OUT, flush=True)
