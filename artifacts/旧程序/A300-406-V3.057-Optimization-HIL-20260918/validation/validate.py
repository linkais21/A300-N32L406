from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
records = []

def run(label, command, cwd=ROOT, timeout=120):
    with (OUT / (label + '.log')).open('w', encoding='utf-8') as log:
        result = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    records.append(dict(label=label, command=command, cwd=str(cwd.relative_to(ROOT)), exit_code=result.returncode))
    (OUT / 'commands.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    print(label, result.returncode, flush=True)
    return result.returncode

files = [p for directory in ('src', 'include', 'ldscript', 'bootloader', 'third_party', 'sdk', 'tools')
         for p in (ROOT / directory).rglob('*') if p.is_file() and p.suffix in ('.c', '.h', '.s', '.ld', '.py')
         and 'build' not in p.parts and '__pycache__' not in p.parts]
files += [ROOT / 'Makefile', ROOT / 'bootloader/Makefile', ROOT / 'release_identity.json']
hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
(OUT / 'source-hashes.json').write_text(json.dumps(hashes, indent=2))

tests = '''release_identity_contract build_version_refresh debug_log_levels heap_bounds
dev_release_manifest lto_stack_guard flash_gate_build platform_trust_anchor
feature_guards nmea_replay jt808_params_wire jt808_dual_session jt808_first_location
jt808_boot_terminal_info terminal_identity mileage_persistence size_trial
log_platform_wire log_platform_contract blind_zone_store blind_zone_replay
ext_flash_store_host ext_flash_layout internal_flash_layout
fota_check_parser fota_checkpoint_powercut fota_modem_handoff fota_platform_flow
agnss_vendor_stream agnss_scheduler agnss_snapshot agnss_workspace_ownership
bootloader_bcr_failclosed bootloader_platform_contract'''.split()
for name in tests:
    run('test_' + name, [sys.executable, 'tools/tests/test_' + name + '.py'])

build = OUT.relative_to(ROOT).as_posix() + '/app'
run('app-build', ['mingw32-make', '-j4', 'BUILD=' + build, 'size', 'flash-guard'], timeout=240)
run('release-gate', ['mingw32-make', 'BUILD=' + build, 'release-gate'])
run('libc-parser', [sys.executable, 'tools/libc_parser_guard.py', build + '/a300_firmware.map'])
bootdir = '../' + OUT.relative_to(ROOT).as_posix() + '/boot'
overlay = (ROOT / 'bootloader/Makefile').read_text().replace('build', bootdir)
(OUT / 'boot.mk').write_text(overlay)
run('boot-build', ['mingw32-make', '-j4', '-f', '../' + OUT.relative_to(ROOT).as_posix() + '/boot.mk', 'all'], ROOT / 'bootloader', timeout=240)
run('boot-ram', [sys.executable, 'tools/map_ram_guard.py', 'bootloader', OUT.relative_to(ROOT).as_posix() + '/boot/bootloader.map'])
changed = [name for name, digest in hashes.items() if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
assert not changed, changed
print('Inputs unchanged; failures:', [r['label'] for r in records if r['exit_code']], flush=True)
