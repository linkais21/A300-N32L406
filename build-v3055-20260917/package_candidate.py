from pathlib import Path
import hashlib, importlib.util, json, re, shutil, struct, subprocess, sys, zipfile, zlib

ROOT=Path(__file__).resolve().parents[1]
WORK=Path(__file__).resolve().parent
OUT=ROOT/'artifacts/A300-406-V3.055-Test-20260917'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
host=json.loads((WORK/'validation/host-results.json').read_text())
assert len(host)==64, len(host)
assert all(r['exit_code']==0 for r in host)
extra=json.loads((WORK/'validation/additional-results.json').read_text())
assert all(r['exit_code']==0 for r in extra)
for name in ('app-build','boot-build'):
    assert not re.search(rb'warning:', (WORK/'validation'/f'{name}.log').read_bytes(), re.I)
gate=(WORK/'validation/release-gate.log').read_text(errors='replace')
assert 'release-guard: PASS' in gate and 'incomplete stack evidence' in gate
hashes=json.loads((WORK/'source-hashes.json').read_text())
for name,digest in hashes.items():
    assert sha(ROOT/name)==digest, 'source changed since build: '+name
    assert sha(WORK/'source'/name)==digest, name
spec=importlib.util.spec_from_file_location('builder',ROOT/'tools/build_dev_release.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
identity=b.release_identity()
assert identity['firmware_version_counter']==3055
app=(WORK/'a300_firmware.bin').read_bytes()
bootdir=WORK/'source/bootloader/build'
boot=(bootdir/'bootloader.bin').read_bytes()
assert identity['firmware_version'].encode() in app
stamp=re.search(r'FW_BUILD_NUMBER\s+"([0-9]{12})"',(ROOT/'include/build_version.h').read_text()).group(1)
assert stamp.encode() in app
assert sha(WORK/'a300_firmware.bin')==json.loads((WORK/'flash-capacity.json').read_text())['bin_sha256']
combined=b.build_combined(boot,app)
OUT.mkdir(exist_ok=False)
files={}
def copy(src,dst):
    shutil.copy2(src,OUT/dst)
    files[dst]=dict(bytes=(OUT/dst).stat().st_size,sha256=sha(OUT/dst))
for suffix in ('bin','hex','elf','map'):
    copy(WORK/f'a300_firmware.{suffix}',f'App-N32L406CBL7.{suffix}')
    copy(bootdir/f'bootloader.{suffix}',f'Bootloader-N32L406CBL7.{suffix}')
(OUT/'SWD-Combined-N32L406CBL7.bin').write_bytes(combined)
commands=[]
def run(name,cmd):
    p=subprocess.run([str(x) for x in cmd],cwd=ROOT,capture_output=True,timeout=120)
    (WORK/'validation'/f'{name}.log').write_bytes(p.stdout+p.stderr)
    commands.append(dict(name=name,command=[str(x) for x in cmd],exit_code=p.returncode))
    assert p.returncode==0,name
objcopy=ROOT/'.toolchain/bin/arm-none-eabi-objcopy.exe'
run('combined-hex',[objcopy,'-I','binary','-O','ihex','--change-addresses','0x08000000',OUT/'SWD-Combined-N32L406CBL7.bin',OUT/'SWD-Combined-N32L406CBL7.hex'])
run('hex-roundtrip',[objcopy,'-I','ihex','-O','binary',OUT/'SWD-Combined-N32L406CBL7.hex',WORK/'combined-roundtrip.bin'])
assert (WORK/'combined-roundtrip.bin').read_bytes()==combined
assert combined[0x6000:]==app and len(combined)<=131072
ota=OUT/'A300-406-OTA-V3055.bin'
run('ota-package',[sys.executable,ROOT/'tools/gen_a300_ota_image.py','--input',OUT/'App-N32L406CBL7.bin','--output',ota,'--version-code','3055'])
blob=ota.read_bytes()
magic,version,length,crc,product,reserved=struct.unpack_from('<IIIII12s',blob)
assert (magic,version,length,crc,product,reserved)==(0xA300B007,3055,len(app),zlib.crc32(app)&0xffffffff,0x41333030,bytes(12))
assert blob[32:]==app
for n in ('SWD-Combined-N32L406CBL7.bin','SWD-Combined-N32L406CBL7.hex',ota.name):
    files[n]=dict(bytes=(OUT/n).stat().st_size,sha256=sha(OUT/n))
(WORK/'validation/package-results.json').write_text(json.dumps(commands,indent=2),encoding='utf-8')
shutil.copytree(WORK/'validation',OUT/'validation')
for n in ('flash-capacity.json','flash-build-profile.json','stack-evidence.json','stack-analysis.json','production-wire.txt','source-hashes.json'):
    shutil.copy2(WORK/n,OUT/'validation'/n)
shutil.copytree(WORK/'source',OUT/'source',ignore=shutil.ignore_patterns('build','__pycache__'))
copy(ROOT/'docs/v3055-cleanup-review-20260917.md','CLEANUP-REVIEW.md')
manifest=dict(firmware_version=identity['firmware_version'],version_counter=3055,mcu='N32L406CBL7',
    release_approved=False,purpose='User-requested SWD and OTA bench test candidate',
    release_gate='FAIL: incomplete whole-program stack/heap/exception evidence',
    host_tests_passed=len(host),build_stamp=stamp,app_bytes=len(app),app_flash_free=106496-len(app),
    signing='platform-detached; OTA upload image is unsigned',
    addresses=dict(combined='0x08000000',app='0x08006000'),artifacts=files,
    baseline='A300-406-V3.054-V150-Fix-20260917',git_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    git_dirty=True,source_snapshot_sha256=sha(WORK/'source-hashes.json'))
(OUT/'MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
readme='''# A300-406 V3.055 烧录 / OTA 测试候选包

版本：T360-A300_406_20260823000000,V3.055；OTA 计数：3055。
目标：A300-T9 / N32L406CBL7，128 KiB Flash、24 KiB SRAM。不是 N32G452 固件。

## 直接烧录

优先使用 SWD-Combined-N32L406CBL7.hex（自带地址）。若用同名 BIN，起始地址必须是 **0x08000000**。这是 Bootloader + 出厂初始化标记 + App。写后校验并复位。

**完整烧录首次启动会清除设备配置和升级状态。先保存设备参数，启动后重新写入服务器、APN、终端 ID、设备 OTA Key 等配置。** 不要把完整 BIN 写到 App 地址 0x08006000。单独 App 文件供分析/已有 Boot 场景，不替代本次完整烧录步骤。

## OTA 升级测试

在当前已可联网、已配置设备 Key 的 V3.054 设备上测试。向现有 HTTP FOTA 平台上传 **A300-406-OTA-V3055.bin**，选择型号 **A300-406**、版本 V3.055、计数 3055。平台需使用与设备信任根匹配的签名密钥提供 detached 签名和现有 HTTP 更新契约；上传包本身未签名，不包含私钥。不上传 Combined 镜像或裸 App 作为 OTA 包。

若先烧录 V3.055，再测试同版 V3.055 OTA，正常版本策略可能拒绝，因为计数没有增加。建议一台设备直接烧录验证，另一台保留 V3.054 做 OTA；或在首次升到 V3.055 之前先做 OTA。不要关闭版本/签名校验以强刷。

确认下载与断点续传、CRC/签名、安装后上报 V3.055、既有配置保持；异常断电与回退仅在样机治具上测试。未执行线上部署、上传、真实烧录或真实 OTA。

## 配套产测

使用工作区 生产测试工具/A300ProductionTester/bin/A300ProductionTester.exe 当前 V1.6.0。版本预设手动改为 **V3.055** 或上述完整字符串；不自动覆盖旧订单。并行检测、APN 名称应答、版本匹配及 Gsensor 连续确认均保留。不再推荐旧 V1.5.0 工具。

## 清理与验证

参见 CLEANUP-REVIEW.md：保留从指定 Fix 起点到 Fix6 的有效修复，清理旧 APN 凭据回显覆盖分支，修复身份测试夹具。历史镜像和源文件未删除。

主机回归、App/Boot 构建、Flash 容量、发布身份、签名信任根、HEX 往返、OTA 头/CRC/版本及包体一致性验证记录位于 validation。源快照位于 source。

**release_approved=false：完整 RAM/栈发布门禁未通过，原因是全程序栈/堆/中断异常上界证据不完整。该问题未通过放宽门禁掩盖。** Boot 静态容量通过不等于运行栈已验证。本包仅供用户要求的样机测试，不能据此批准量产。

需要实机/HIL 验证：真实烧录启动、产测全流程、GNSS/继电器/低功耗唤醒、盲区断网与复位恢复、OTA 升级/配置保持/失败回退、堆栈水位。
'''
(OUT/'README.md').write_text(readme,encoding='utf-8')
(OUT/'SHA256SUMS.txt').write_text(''.join(sha(p)+'  '+p.relative_to(OUT).as_posix()+'\n' for p in sorted(OUT.rglob('*')) if p.is_file()),encoding='utf-8')
archive=OUT.parent/(OUT.name+'.zip')
assert not archive.exists()
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for p in OUT.rglob('*'):
        if p.is_file(): z.write(p,p.relative_to(OUT.parent))
with zipfile.ZipFile(archive) as z: assert z.testzip() is None
Path(str(archive)+'.sha256').write_text(sha(archive)+'  '+archive.name+'\n',encoding='ascii')
print('PACKAGED',archive)
print('App',len(app),'Combined',len(combined),'OTA',len(blob),'SHA256',sha(archive))
