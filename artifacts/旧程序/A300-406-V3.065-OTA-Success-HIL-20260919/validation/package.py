from pathlib import Path
import difflib, hashlib, json, shutil, struct, subprocess, sys, zipfile, zlib
WORK=Path(__file__).resolve().parent
ROOT=WORK.parents[1]
OUT=ROOT/'artifacts/A300-406-V3.065-OTA-Success-HIL-20260919'
APP=WORK/'app'
BOOT=WORK/'source/bootloader/build'
sys.path.insert(0,str(ROOT/'tools'))
from build_dev_release import build_combined,validate_app_vectors

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

# Header documentation changed after the original snapshot; verify that only
# the intended header update is imported, then freeze all source identities.
shutil.copy2(ROOT/'include/fota.h',WORK/'source/include/fota.h')
hashes=json.loads((WORK/'source-hashes.json').read_text())
hashes['include/fota.h']=sha(ROOT/'include/fota.h')
for n,h in hashes.items():
    assert sha(ROOT/n)==h and sha(WORK/'source'/n)==h,n
(WORK/'source-hashes.json').write_text(json.dumps(hashes,indent=2))
changed=[p.relative_to(WORK/'before').as_posix() for p in (WORK/'before').rglob('*') if p.is_file()]
patch=''.join(''.join(difflib.unified_diff((WORK/'before'/n).read_text(encoding='utf-8').splitlines(True),
                (ROOT/n).read_text(encoding='utf-8').splitlines(True),fromfile='before/'+n,tofile='after/'+n)) for n in changed)
(WORK/'task.patch').write_text(patch,encoding='utf-8')
records={p.name.removesuffix('.command.json'):json.loads(p.read_text()) for p in WORK.glob('*.command.json')}
for name,record in records.items():
    assert record['exit_code']==(2 if name=='release-gate' else 0),(name,record)
assert all(n in records for n in ['build','boot-build','release-gate','platform-wire','fota_success_report','diff-check'])
for n in ['build','boot-build']:
    assert b'warning:' not in (WORK/(n+'.log')).read_bytes().lower()
identity=json.loads((ROOT/'release_identity.json').read_text())
assert identity['firmware_version_counter']==3065
app=(APP/'a300_firmware.bin').read_bytes();boot=(BOOT/'bootloader.bin').read_bytes()
assert identity['firmware_version'].encode() in app
assert b'V3.064' not in app
validate_app_vectors(app)
cap=json.loads((APP/'flash-capacity.json').read_text())
assert cap['status']=='passed' and cap['bin_sha256']==sha(APP/'a300_firmware.bin')
stack=json.loads((APP/'stack-analysis.json').read_text())
assert stack['status']=='incomplete' and stack['elf_sha256']==sha(APP/'a300_firmware.elf')
combined=build_combined(boot,app)
assert len(combined)<=131072
OUT.mkdir(exist_ok=False)
objcopy=ROOT/'.toolchain/bin/arm-none-eabi-objcopy.exe'
for label,body,origin in [('App',app,0x08006000),('Bootloader',boot,0x08000000),('SWD-Combined',combined,0x08000000)]:
    p=OUT/(label+'-V3065.bin');p.write_bytes(body)
    h=p.with_suffix('.hex')
    subprocess.run([str(objcopy),'-I','binary','-O','ihex','--change-addresses',hex(origin),str(p),str(h)],check=True)
    verify=WORK/(label+'-hex-check.bin')
    subprocess.run([str(objcopy),'-I','ihex','-O','binary',str(h),str(verify)],check=True)
    assert verify.read_bytes()==body
for folder,stem,label in [(APP,'a300_firmware','App'),(BOOT,'bootloader','Bootloader')]:
    for ext in ['elf','map']:shutil.copy2(folder/(stem+'.'+ext),OUT/(label+'-V3065.'+ext))
ota=OUT/'A300-406-OTA-V3065.bin'
subprocess.run([sys.executable,str(ROOT/'tools/gen_a300_ota_image.py'),'--input',str(OUT/'App-V3065.bin'),
                '--output',str(ota),'--version-code','3065'],check=True)
wire=ota.read_bytes()
assert struct.unpack_from('<5I12s',wire)==(0xA300B007,3065,len(app),zlib.crc32(app)&0xffffffff,0x41333030,bytes(12))
assert wire[32:]==app
valid=OUT/'validation';valid.mkdir()
for p in WORK.iterdir():
    if p.is_file() and p.suffix in ['.log','.json','.patch','.py']:shutil.copy2(p,valid/p.name)
for n in ['flash-capacity.json','stack-analysis.json','stack-evidence.json','flash-build-profile.json']:
    shutil.copy2(APP/n,valid/n)
shutil.copy2(ROOT/'docs/ota-success-v3065-20260919.md',OUT/'CHANGELOG.md')
shutil.copy2(ROOT/'release_identity.json',OUT/'release_identity.json')
upload=dict(file=ota.name,deviceModel='A300-406',versionCode=3065,versionName=identity['firmware_version'],
            size=len(wire),sha256=sha(ota),active=False,mandatory=False,signing='platform-detached',
            releaseNotes='HIL candidate: post-confirmation OTA success report; stationary lock retained. RAM release gate incomplete.')
(OUT/'OTA-upload.json').write_text(json.dumps(upload,indent=2)+'\n')
manifest=dict(version=identity['firmware_version'],versionCode=3065,release_approved=False,hardware_verified=False,
              stationary_lock_user_pass=True,release_gate_exit=2,release_gate_reason='Incomplete whole-program stack/heap/IRQ evidence',
              app_bytes=len(app),ota_bytes=len(wire),flash_remaining=cap['remaining_bytes'],
              tests_passed=sum(n.startswith('fota_') or n in [] for n in records),
              files={p.name:dict(size=p.stat().st_size,sha256=sha(p)) for p in OUT.iterdir() if p.is_file()})
manifest['host_test_scripts_passed']=sum(len(v['command'])>1 and v['command'][1].startswith('tools/tests/test_') for v in records.values())
manifest.pop('tests_passed')
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(OUT/'README.md').write_text('''# A300-406 V3.065 OTA 成功上报候选包

OTA 上传文件：`A300-406-OTA-V3065.bin`，deviceModel=A300-406，versionCode=3065。
升级后的 ACTIVE 版本联网后上报 success；断网/响应丢失保留记录并有限次补报。
静止锁点用户已确认 PASS，本版保留。

App/Boot 编译及相关自动测试通过，但完整 RAM 发布门禁未通过，详见 CHANGELOG.md。
本包为 HIL 候选，未实机验证、未上传、未部署，不代表量产发布批准。
平台令牌超过 48 小时不能补报；旧版 compact URL 记录可恢复令牌。
SWD-Combined 包含首次启动工厂初始化记录；现有设备保留配置升级请使用 OTA 文件。
SHA256SUMS.txt 包含本目录文件校验值。validation 保留命令、结果和源码哈希。
''',encoding='utf-8')
all_files=sorted(p for p in OUT.rglob('*') if p.is_file())
(OUT/'SHA256SUMS.txt').write_text(''.join(sha(p)+'  '+p.relative_to(OUT).as_posix()+'\n' for p in all_files))
archive=OUT.with_suffix('.zip')
assert not archive.exists()
with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
    for p in OUT.rglob('*'):
        if p.is_file():z.write(p,OUT.name+'/'+p.relative_to(OUT).as_posix())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert z.read(OUT.name+'/'+ota.name)==wire
archive.with_suffix('.zip.sha256').write_text(sha(archive)+'  '+archive.name+'\n')
print(json.dumps(dict(package=str(OUT),ota_bytes=len(wire),app_bytes=len(app),remaining=cap['remaining_bytes'],
                     ota_sha256=sha(ota),host_tests=manifest['host_test_scripts_passed']),indent=2))
