from pathlib import Path
import hashlib, importlib.util, json, os, shutil, subprocess, sys, zipfile
ROOT=Path(__file__).resolve().parents[1]
BUILD=Path(__file__).resolve().parent
OUT=ROOT/'artifacts/A300-406-V3.054-V150-Fix-20260917'
LOG=BUILD/'validation';LOG.mkdir(exist_ok=True)
MAKE=ROOT.parent/'tools/w64devkit/w64devkit/bin/mingw32-make.exe'
TC=ROOT/'.toolchain/bin'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
results=[]
def run(name,args,allowed=(0,)):
    p=subprocess.run([str(x) for x in args],cwd=ROOT,capture_output=True)
    (LOG/(name+'.log')).write_bytes(p.stdout+p.stderr)
    results.append({'name':name,'command':[str(x) for x in args],'exit_code':p.returncode})
    (LOG/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(name,p.returncode,flush=True)
    assert p.returncode in allowed,name
    return p
os.environ['A300_V150_WIRE']=str(BUILD/'v150-wire.txt')
for test in ('test_at_config_serial_f39','test_f39_parser','test_f39_config','test_f39_dualset','test_f39_actions','test_f39_end_to_end','test_production_test','test_production_gnss','test_at_config_handoff','test_feature_guards'):
    run(test,[sys.executable,'tools/tests/'+test+'.py'])
run('original-v150-exe',['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File','tools/tests/test_v150_binary.ps1','-FirmwareReplies',BUILD/'v150-wire.txt'])
run('release-guard',[MAKE,'-s','release-guard','BUILD='+BUILD.name])
p=run('release-gate',[MAKE,'-s','release-gate','BUILD='+BUILD.name],(2,))
assert b'incomplete stack evidence' in p.stdout+p.stderr
run('platform-trust',[sys.executable,'tools/tests/test_platform_trust_anchor.py'])
run('diff-check',['git','diff','--check','--','src/at_config.c','src/f39_command.c','tools/tests/test_at_config_serial_f39.py','tools/tests/test_f39_end_to_end.py'])
old=ROOT/'build-production-package-20260917'
hashes=json.loads((old/'validation/source-hashes.json').read_text())
# Reuse the exact previously built Bootloader only if all its possible inputs
# are unchanged (including SDK, crypto, shared headers and linker scripts).
for n,h in hashes.items():
    if n.startswith(('bootloader/','include/','third_party/','sdk/')) or n=='src/firmware_signature.c':
        assert sha(ROOT/n)==h,n
spec=importlib.util.spec_from_file_location('builder',ROOT/'tools/build_dev_release.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
boot=old/'source/bootloader/build'
app=(BUILD/'a300_firmware.bin').read_bytes()
combined=b.build_combined((boot/'bootloader.bin').read_bytes(),app)
assert len(app)<=106496 and len(combined)<=131072
OUT.mkdir(exist_ok=False)
(OUT/'SWD-Combined-N32L406CBL7.bin').write_bytes(combined)
run('combined-hex',[TC/'arm-none-eabi-objcopy.exe','-I','binary','-O','ihex','--change-addresses','0x08000000',OUT/'SWD-Combined-N32L406CBL7.bin',OUT/'SWD-Combined-N32L406CBL7.hex'])
run('hex-roundtrip',[TC/'arm-none-eabi-objcopy.exe','-I','ihex','-O','binary',OUT/'SWD-Combined-N32L406CBL7.hex',BUILD/'roundtrip.bin'])
assert (BUILD/'roundtrip.bin').read_bytes()==combined
assert combined[0x6000:]==app
shutil.copytree(LOG,OUT/'validation')
for n in ('boot-build.log','boot-ram.log','source-hashes.json'):
    shutil.copy2(old/'validation'/n,OUT/'validation'/('reused-'+n))
for n in ('flash-capacity.json','flash-build-profile.json','stack-evidence.json','stack-analysis.json','v150-wire.txt','package_fix.py'):
    shutil.copy2(BUILD/n,OUT/'validation'/n)
for folder in ('src','include','ldscript'):
    shutil.copytree(ROOT/folder,OUT/'source'/folder)
for n in ('Makefile','release_identity.json','tools/tests/test_at_config_serial_f39.py','tools/tests/test_f39_end_to_end.py','tools/tests/test_v150_binary.ps1'):
    dest=OUT/'source'/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/n,dest)
(OUT/'diagnostics').mkdir()
for ext in ('bin','elf','hex','map'):
    shutil.copy2(BUILD/('a300_firmware.'+ext),OUT/'diagnostics'/('App.'+ext))
    shutil.copy2(boot/('bootloader.'+ext),OUT/'diagnostics'/('Bootloader.'+ext))
shutil.copy2(BUILD/'README.md',OUT/'README.md')
manifest={'release_approved':False,'release_gate':'FAIL: incomplete stack/heap/exception evidence',
 'purpose':'V1.5.0 parameter compatibility fix, user-requested HIL image','firmware_version':'V3.054',
 'app_bytes':len(app),'app_free_bytes':106496-len(app),'combined_bytes':len(combined),'bin_address':'0x08000000',
 'original_exe_sha256':sha(ROOT.parent/'生产测试工具/A300ProductionTester/bin/A300ProductionTester.exe'),
 'verified':'Original EXE ParseParam/IsSuccess against real C console responses; no GUI/HIL',
 'changed_sources':['src/at_config.c','src/f39_command.c'],'bootloader':'Unchanged verified build from prior package'}
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
print(manifest,flush=True)
print(archive,flush=True)
