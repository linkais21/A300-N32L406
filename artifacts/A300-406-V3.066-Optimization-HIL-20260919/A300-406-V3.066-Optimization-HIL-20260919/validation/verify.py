from pathlib import Path
import json, os, subprocess, sys, time
WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
MAKE = ROOT.parent / 'tools/w64devkit/w64devkit/bin/make.exe'
os.environ['PATH'] = str(ROOT.parent / 'tools/w64devkit/w64devkit/bin') + os.pathsep + os.environ['PATH']
os.environ['PYTHONUTF8'] = '1'

def run(name, command, cwd=ROOT, expected=0):
    start = time.time()
    with (WORK / (name + '.log')).open('wb') as log:
        p = subprocess.run([str(x) for x in command], cwd=cwd, stdout=log, stderr=subprocess.STDOUT, timeout=600)
    record = dict(command=[str(x) for x in command], cwd=str(cwd), exit_code=p.returncode, elapsed_seconds=time.time()-start)
    (WORK / (name + '.command.json')).write_text(json.dumps(record, indent=2))
    print(name, p.returncode, flush=True)
    if p.returncode != expected:
        print((WORK / (name + '.log')).read_text(encoding='utf-8', errors='replace')[-6000:])
        raise SystemExit(1)

tests = ['flash_config_v3','flash_config_migration','vibration_sensitivity',
 'fota_key_config','fota_success_report','fota_platform_flow',
 'jt808_dual_session','jt808_session','jt808_session_send_failure',
 'jt808_send_failure_contract','jt808_registration_tx','jt808_first_location',
 'jt808_boot_terminal_info','jt808_params','jt808_params_wire',
 'jt808_text_command','terminal_reset','text_ack_order','remote_relay',
 'terminal_identity','at_config_serial_f39','f39_config','f39_dualset',
 'f39_end_to_end','cfg_query_contract','work_mode_jt808_contract',
 'blind_zone_store','blind_zone_replay','ext_flash_store_host',
 'ext_flash_layout','feature_guards','release_identity_contract',
 'build_version_refresh','dev_release_manifest','fota_package','platform_trust_anchor',
 'gps_report_filter','gps_report_wire']
for test in tests:
    run(test, [sys.executable, 'tools/tests/test_' + test + '.py'])
common = [MAKE, 'SHELL=cmd.exe', '-o', 'include/build_version.h',
          'BUILD=build/optimization-v3066-20260919/app', 'TOOLCHAIN_DIR=' + (ROOT / '.toolchain/bin').as_posix()]
run('build', common + ['-j4', 'all'])
run('boot-build', [MAKE, 'SHELL=cmd.exe', 'TOOLCHAIN_ROOT=' + (ROOT / '.toolchain/bin').as_posix(), '-j4', 'all'], WORK / 'source/bootloader')
run('release-gate', common + ['release-gate'], expected=2)
run('platform-trust-guard', common + ['platform-trust-guard'])
run('frame-budget', [sys.executable, 'tools/tests/test_ram01_frame_budget.py', WORK / 'app'])
run('libc-parser', [sys.executable, 'tools/libc_parser_guard.py', WORK / 'app/a300_firmware.map'])
run('boot-ram', [sys.executable, 'tools/map_ram_guard.py', 'bootloader', WORK / 'source/bootloader/build/bootloader.map'])
run('diff-check', ['git', 'diff', '--check', '--', 'release_identity.json', 'include/build_version.h', 'include/config.h', 'tools/release_guard.py', 'tools/tests/test_release_identity_contract.py'])
