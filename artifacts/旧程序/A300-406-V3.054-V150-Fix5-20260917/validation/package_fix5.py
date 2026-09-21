"""Freeze current App and freshly matched Bootloader for requested bench test."""
from pathlib import Path
import hashlib, importlib.util, json, os, shutil, subprocess, sys, zipfile
ROOT=Path(__file__).resolve().parents[1]
BUILD=Path(__file__).resolve().parent
WORK=ROOT/'build-production-fix5-package-20260917'
OUT=ROOT/'artifacts/A300-406-V3.054-V150-Fix5-20260917'
WORK.mkdir(exist_ok=True)
LOG=WORK/'validation';LOG.mkdir(exist_ok=True)
MAKE=ROOT.parent/'tools/w64devkit/w64devkit/bin/mingw32-make.exe'
TC=ROOT/'.toolchain/bin'
results=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(name,args,cwd=ROOT,allowed=(0,)):
    p=subprocess.run([str(x) for x in args],cwd=cwd,capture_output=True)
    (LOG/(name+'.log')).write_bytes(p.stdout+p.stderr)
    results.append({'name':name,'command':[str(x) for x in args],'exit_code':p.returncode})
    (LOG/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(name,p.returncode,flush=True)
    assert p.returncode in allowed,name
    return p
os.environ['A300_SENSOR_WIRE']=str(WORK/'sensor-wire.txt')
run('sensor-wire',[sys.executable,'tools/tests/test_production_test.py','--wire-output',WORK/'sensor-wire.txt'])
os.environ['A300_V150_WIRE']=str(WORK/'v150-wire.txt')
for t in ('test_at_config_serial_f39','test_f39_parser','test_f39_config','test_f39_dualset','test_f39_actions','test_f39_end_to_end',
          'test_gps_huada_output','test_gps_huada_gsv','test_production_test','test_production_gnss','test_nmea_replay','test_gps_drop_diagnostics','test_gps_tx_bounded','test_gps_ntp_apply','test_production_adc','test_production_relay','test_at_config_handoff','test_feature_guards',
          'test_log_platform_wire','test_log_platform_contract','test_build_version_refresh','test_release_identity_contract',
          'test_jt808_dual_session','test_blind_zone_store','test_blind_zone_replay','test_blind_zone_ack_channel',
          'test_corner_blind_zone_replay','test_ext_flash_layout','test_ext_flash_store_host'):
    run(t,[sys.executable,'tools/tests/'+t+'.py'])
run('original-v150-exe',['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File','tools/tests/test_v150_binary.ps1','-FirmwareReplies',WORK/'v150-wire.txt'])
run('release-guard',[MAKE,'-s','release-guard','BUILD='+BUILD.name])
p=run('release-gate',[MAKE,'-s','release-gate','BUILD='+BUILD.name],allowed=(2,))
assert b'incomplete stack evidence' in p.stdout+p.stderr
run('platform-trust',[sys.executable,'tools/tests/test_platform_trust_anchor.py'])
run('terminal-identity-known-failure',[sys.executable,'tools/tests/test_terminal_identity.py'],allowed=(1,))
changed=['src/production_test.c','src/gps.c','include/gps.h','tools/tests/test_production_test.py','tools/tests/test_production_gnss.py','tools/tests/test_v150_binary.ps1','Makefile','gen_version.ps1','src/at_config.c','src/f39_command.c','src/f39_config_adapter.c','src/jt808.c',
         'src/blind_zone.c','include/blind_zone.h','src/main.c','src/log_platform.c','tools/build_dev_release.py','tools/release_guard.py',
         'tools/tests/test_at_config_serial_f39.py','tools/tests/test_f39_end_to_end.py','tools/tests/test_build_version_refresh.py',
         'tools/tests/test_jt808_dual_session.py','tools/tests/test_blind_zone_store.py','tools/tests/test_blind_zone_replay.py','tools/tests/test_terminal_identity.py']
run('diff-check',['git','diff','--check','--']+changed)
snapshot=WORK/'source';snapshot.mkdir(exist_ok=False)
for folder in ('src','include','sdk','third_party','ldscript','tools'):
    shutil.copytree(ROOT/folder,snapshot/folder,ignore=shutil.ignore_patterns('__pycache__'))
for folder in ('src','include','ldscript'):
    shutil.copytree(ROOT/'bootloader'/folder,snapshot/'bootloader'/folder)
shutil.copy2(ROOT/'bootloader/Makefile',snapshot/'bootloader/Makefile')
for name in ('Makefile','gen_version.ps1','release_identity.json'):
    shutil.copy2(ROOT/name,snapshot/name)
source_hashes={p.relative_to(snapshot).as_posix():sha(p) for p in snapshot.rglob('*') if p.is_file() and not p.relative_to(snapshot).as_posix().startswith('bootloader/build/')}
run('boot-build',[MAKE,'-s','-B','all','TOOLCHAIN_ROOT='+TC.as_posix()],cwd=snapshot/'bootloader')
boot=snapshot/'bootloader/build'
run('boot-ram',[sys.executable,'tools/map_ram_guard.py','bootloader',boot/'bootloader.map'])
spec=importlib.util.spec_from_file_location('builder',ROOT/'tools/build_dev_release.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
app=(BUILD/'a300_firmware.bin').read_bytes();combined=b.build_combined((boot/'bootloader.bin').read_bytes(),app)
assert len(app)<=106496 and len(combined)<=131072
stamp=(ROOT/'include/build_version.h').read_text()
import re
build_stamp=re.search(r'FW_BUILD_NUMBER\s+"([0-9]{12})"',stamp).group(1)
assert build_stamp.encode() in app
for n,h in source_hashes.items(): assert sha(ROOT/n)==h,n
OUT.mkdir(exist_ok=False)
(OUT/'SWD-Combined-N32L406CBL7.bin').write_bytes(combined)
run('combined-hex',[TC/'arm-none-eabi-objcopy.exe','-I','binary','-O','ihex','--change-addresses','0x08000000',OUT/'SWD-Combined-N32L406CBL7.bin',OUT/'SWD-Combined-N32L406CBL7.hex'])
run('hex-roundtrip',[TC/'arm-none-eabi-objcopy.exe','-I','ihex','-O','binary',OUT/'SWD-Combined-N32L406CBL7.hex',WORK/'roundtrip.bin'])
assert (WORK/'roundtrip.bin').read_bytes()==combined and combined[0x6000:]==app
shutil.copytree(LOG,OUT/'validation')
shutil.copy2(WORK/'sensor-wire.txt',OUT/'validation/sensor-wire.txt')
shutil.copy2(ROOT/'tools/capture_production_diag.ps1',OUT/'capture_production_diag.ps1')
shutil.copy2(WORK/'v150-wire.txt',OUT/'validation/v150-wire.txt')
for n in ('flash-capacity.json','flash-build-profile.json','stack-evidence.json','stack-analysis.json','package_fix5.py'):
    shutil.copy2(BUILD/n,OUT/'validation'/n)
for n in source_hashes:
    p=OUT/'source'/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(snapshot/n,p)
(OUT/'diagnostics').mkdir()
for ext in ('bin','elf','hex','map'):
    shutil.copy2(BUILD/('a300_firmware.'+ext),OUT/'diagnostics'/('App.'+ext))
    shutil.copy2(boot/('bootloader.'+ext),OUT/'diagnostics'/('Bootloader.'+ext))
shutil.copy2(ROOT/'docs/production-fix5-20260917.md',OUT/'README.md')
manifest={'release_approved':False,'release_gate':'FAIL: incomplete stack/heap/exception evidence','firmware_version':'V3.054',
 'build_stamp':build_stamp,'app_bytes':len(app),'app_free_bytes':106496-len(app),'combined_bytes':len(combined),
 'bin_address':'0x08000000','sim_status_field':'6F (user confirmed)', 'hardware_verified':False,
 'original_exe_sha256':sha(ROOT.parent/'生产测试工具/A300ProductionTester/bin/A300ProductionTester.exe'),
 'known_test_failure':'terminal identity fixture missing dependencies', 'gps_hardware_cn_issue':'CFG-MSG and dual-band parsing corrected against vendor protocol/samples; HIL pending',
 'changes':['Huada F1D9 CFG-MSG init and wake','Huada cross-band GSV page parsing without duplicate band counting','Gsensor INT field for original EXE','SOS LEVEL and ACTIVE for original EXE','bounded GNSS trace and counters','APN AUTO empty credentials','work-mode offline FIFO append','durable event identity','SIM status and ICCID','startup compile timestamp'],
 'source_hashes':source_hashes}
(OUT/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
files=[p for p in sorted(OUT.rglob('*')) if p.is_file()]
lines=[sha(p)+'  '+p.relative_to(OUT).as_posix() for p in files]
(OUT/'SHA256SUMS.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
for line in lines:
    h,n=line.split('  ',1);assert sha(OUT/n)==h,n
archive=Path(str(OUT)+'.zip')
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
    for p in OUT.rglob('*'):
        if p.is_file():z.write(p,p.relative_to(OUT.parent))
with zipfile.ZipFile(archive) as z: assert z.testzip() is None
Path(str(archive)+'.sha256').write_text(sha(archive)+'  '+archive.name+'\n')
print('PACKAGED',archive,'App free',106496-len(app),'build',build_stamp,flush=True)
