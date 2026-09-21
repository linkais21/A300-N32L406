from pathlib import Path
import hashlib, importlib.util, json, shutil, struct, subprocess, sys, zipfile

ROOT=Path(__file__).resolve().parents[1]
WORK=Path(__file__).resolve().parent
OUT=ROOT/'artifacts/A300-406-V3.054-Production-HIL-20260917'
APP=ROOT/'build-production-20260917'
BOOT=WORK/'source/bootloader/build'
TC=ROOT/'.toolchain/bin'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args): return subprocess.check_output([str(x) for x in args],cwd=ROOT)

hashes=json.loads((WORK/'validation/source-hashes.json').read_text())
for name,h in hashes.items():
    assert sha(ROOT/name)==h, name
    assert sha(WORK/'source'/name)==h,name
delivery=json.loads((APP/'DELIVERY_INPUTS.json').read_text(encoding='utf-8'))
for group in ('inputs','outputs'):
    for name,h in delivery[group].items(): assert sha(ROOT.parent/name)==h,name
results=json.loads((WORK/'validation/results.json').read_text())
assert all(r['exit_code']==0 for r in results if r['name']!='release-gate')
assert next(r['exit_code'] for r in results if r['name']=='release-gate')==2
assert 'incomplete stack evidence' in (WORK/'validation/release-gate.log').read_text()
spec=importlib.util.spec_from_file_location('builder',ROOT/'tools/build_dev_release.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
app=(APP/'a300_firmware.bin').read_bytes();boot=(BOOT/'bootloader.bin').read_bytes()
assert len(app)==100820 and len(app)<=106496
bmsp,breset=struct.unpack_from('<II',boot)
assert 0x20000000<=bmsp<=0x20006000 and bmsp%8==0
assert breset&1 and 0x08000000<=breset<0x08005800
combined=builder.build_combined(boot,app)
assert len(combined)<=131072 and combined[0x6000:]==app
sections=run([TC/'arm-none-eabi-objdump.exe','-h',BOOT/'bootloader.elf']).decode()
assert '.factory_init_request 0000001c  08005800' in sections
OUT.mkdir(exist_ok=False)
(OUT/'SWD-Combined-N32L406CBL7.bin').write_bytes(combined)
run([TC/'arm-none-eabi-objcopy.exe','-I','binary','-O','ihex','--change-addresses','0x08000000',
     OUT/'SWD-Combined-N32L406CBL7.bin',OUT/'SWD-Combined-N32L406CBL7.hex'])
run([TC/'arm-none-eabi-objcopy.exe','-I','ihex','-O','binary',OUT/'SWD-Combined-N32L406CBL7.hex',WORK/'roundtrip.bin'])
assert (WORK/'roundtrip.bin').read_bytes()==combined
details=OUT/'diagnostics';details.mkdir()
for src,stem in [(APP/'a300_firmware','App'),(BOOT/'bootloader','Bootloader')]:
    for ext in ('bin','hex','elf','map'):
        shutil.copy2(src.with_suffix('.'+ext),details/(stem+'.'+ext))
shutil.copytree(WORK/'validation',OUT/'validation')
shutil.copy2(APP/'DELIVERY_INPUTS.json',OUT/'validation/previous-delivery-inputs.json')
for name in ('flash-capacity.json','flash-build-profile.json','stack-evidence.json','stack-analysis.json'):
    shutil.copy2(APP/name,OUT/'validation'/name)
shutil.copy2(ROOT/'docs/production-test-20260917.md',OUT/'validation/implementation-report.md')
for name in hashes:
    target=OUT/'source'/name;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(WORK/'source'/name,target)
for name in ('prepare.py','package.py'):
    shutil.copy2(WORK/name,OUT/'validation'/name)
tool=ROOT.parent/'生产测试工具/A300ProductionTester'
identity={
 'purpose':'User-requested complete SWD image for bench/HIL testing',
 'release_approved':False,'release_gate':'FAIL: incomplete whole-program stack/heap/exception evidence',
 'hardware_verified':False,'flashed':False,'mcu':'N32L406CBL7',
 'firmware_version':builder.release_identity()['firmware_version'],
 'package_identity':OUT.name,'git_revision':run(['git','rev-parse','HEAD']).decode().strip(),
 'git_dirty':True,'flash_base':'0x08000000','app_base':'0x08006000',
 'app_bytes':len(app),'app_free_bytes':106496-len(app),'combined_bytes':len(combined),
 'factory_init':'First boot resets configuration slots, BCR and FOTA checkpoint/auth slots',
 'tester_candidate':{'version':'1.6.0','sha256':sha(tool/'build-releases/V1.6.0-production-candidate/A300ProductionTester.exe'),
                     'protocol_test':'PASS: actual C responses parsed by current C# protocol and result logic; GUI/HIL not run'},
 'original_tester':{'sha256':sha(tool/'bin/A300ProductionTester.exe'),'compatibility':'Not established; user selection pending'},
 'artifact_checks':['Boot/App vectors','Factory init marker and ELF section','Image size and offsets','HEX to BIN roundtrip','Source and App hashes']}
(OUT/'MANIFEST.json').write_text(json.dumps(identity,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
shutil.copy2(WORK/'README.md',OUT/'README.md')
lines=[sha(p)+'  '+p.relative_to(OUT).as_posix() for p in sorted(OUT.rglob('*')) if p.is_file()]
(OUT/'SHA256SUMS.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
for line in lines:
    h,name=line.split('  ',1);assert sha(OUT/name)==h
archive=OUT.with_suffix('.zip')
# Preserve the full V3.054 directory name; Path.with_suffix would strip it.
archive=Path(str(OUT)+'.zip')
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(OUT.rglob('*')):
        if p.is_file():z.write(p,p.relative_to(OUT.parent))
with zipfile.ZipFile(archive) as z: assert z.testzip() is None
Path(str(archive)+'.sha256').write_text(sha(archive)+'  '+archive.name+'\n')
print(json.dumps(identity,ensure_ascii=False,indent=2))
print(archive)
