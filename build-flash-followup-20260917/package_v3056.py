from pathlib import Path
import sys, json, shutil, subprocess, hashlib, os
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import build_dev_release as release
work=ROOT/'build-v3056-stability-hil'
work.mkdir(exist_ok=False)
for name in ('release_identity.json','include/config.h','include/build_version.h'):
    dst=work/'before'/name;dst.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/name,dst)
identity=json.loads((ROOT/'release_identity.json').read_text())
assert identity['firmware_version_counter']==3055
identity['firmware_revision']=56
identity['firmware_version_counter']=3056
identity['firmware_version']=identity['firmware_version'].replace(',V3.055',',V3.056')
(ROOT/'release_identity.json').write_text(json.dumps(identity,indent=2)+'\n')
release.refresh_build_version()
make=shutil.which('mingw32-make.exe')
records=[]
def run(label,args,cwd=ROOT,expected=0):
    p=subprocess.run(args,cwd=cwd,capture_output=True)
    (work/(label+'.log')).write_bytes(p.stdout+p.stderr)
    records.append({'label':label,'command':args,'exit_code':p.returncode})
    (work/'commands.json').write_text(json.dumps(records,indent=2))
    print(label,p.returncode,flush=True)
    if p.returncode!=expected:raise RuntimeError(label)
run('app',[make,'-s','flash-guard','stack-report','BUILD=build-v3056-stability-hil/app'])
boot=work/'boot';boot.mkdir()
mk=(ROOT/'bootloader/Makefile').read_text().replace('build/','../build-v3056-stability-hil/boot/')
(work/'boot.mk').write_text(mk)
run('boot',[make,'-s','-f','../build-v3056-stability-hil/boot.mk','all'],ROOT/'bootloader')
run('release-gate',[make,'-s','release-gate','BUILD=build-v3056-stability-hil/app'],expected=2)
for test in ('test_ram01_frame_budget','test_platform_trust_anchor','test_release_identity_contract','test_build_version_refresh','test_fota_package','test_dev_release_manifest'):
    args=[sys.executable,'-B','tools/tests/'+test+'.py']
    if test=='test_ram01_frame_budget':args+=['build-v3056-stability-hil/app']
    run(test,args)
run('libc',[sys.executable,'tools/libc_parser_guard.py',str(work/'app/a300_firmware.map')])
run('boot-capacity',[sys.executable,'tools/map_ram_guard.py','bootloader',str(boot/'bootloader.map')])
out=ROOT/'artifacts/A300-406-V3.056-Stability-HIL'
out.mkdir(exist_ok=False)
for prefix,source in [('App',work/'app/a300_firmware'),('Bootloader',boot/'bootloader')]:
    for ext in ('bin','hex','elf','map'):shutil.copy2(source.with_suffix('.'+ext),out/(prefix+'-N32L406CBL7.'+ext))
combined=release.build_combined((out/'Bootloader-N32L406CBL7.bin').read_bytes(),(out/'App-N32L406CBL7.bin').read_bytes())
(out/'Combined-N32L406CBL7.bin').write_bytes(combined)
run('combined-hex',[str(ROOT/'.toolchain/bin/arm-none-eabi-objcopy.exe'),'-I','binary','-O','ihex','--change-addresses','0x08000000',str(out/'Combined-N32L406CBL7.bin'),str(out/'Combined-N32L406CBL7.hex')])
for name in ('flash-capacity.json','stack-analysis.json','stack-evidence.json'):
    shutil.copy2(work/'app'/name,out/name)
shutil.copy2(ROOT/'release_identity.json',out/'release_identity.json')
evidence=out/'validation';evidence.mkdir()
for p in work.glob('*.log'):shutil.copy2(p,evidence/p.name)
shutil.copy2(work/'commands.json',evidence/'commands.json')
hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for d in ('src','include','bootloader/src','bootloader/include') for p in (ROOT/d).rglob('*') if p.is_file()}
(out/'source-hashes.json').write_text(json.dumps(hashes,indent=2))
print('PACKAGE',out,flush=True)
