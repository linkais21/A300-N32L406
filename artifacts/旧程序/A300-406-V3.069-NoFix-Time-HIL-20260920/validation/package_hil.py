"""Assemble the explicitly requested V3069 HIL artifacts, not a release approval."""
from pathlib import Path
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_dev_release import build_combined, validate_app_vectors, validate_factory_init_marker

LOGS = ROOT / 'build-v3069-nofix-validation'
BUILD = ROOT / 'build-v3069-nofix'
OUT = ROOT / 'artifacts/A300-406-V3.069-NoFix-Time-HIL-20260920'
identity = json.loads((ROOT/'release_identity.json').read_text())
assert identity['firmware_version_counter'] == 3069
tests = json.loads((LOGS/'tests.json').read_text())
assert len(tests) == 19 and all(t['exit_code'] == 0 for t in tests)
for component in ('app', 'boot'):
    assert json.loads((LOGS/f'{component}-build-command.json').read_text())['exit_code'] == 0
    assert not re.search(r'warning:|error:', (LOGS/f'{component}-build.log').read_text(), re.I)
gates = json.loads((LOGS/'gates.json').read_text())
assert [g['exit_code'] for g in gates] == [2, 0, 0]
assert 'release-guard: PASS' in (LOGS/'release-gate.log').read_text()
assert 'incomplete stack evidence' in (LOGS/'release-gate.log').read_text()
app = (BUILD/'a300_firmware.bin').read_bytes()
boot = (ROOT/'bootloader/build/bootloader.bin').read_bytes()
assert identity['firmware_version'].encode() in app
validate_app_vectors(app)
validate_factory_init_marker(boot)
combined = build_combined(boot, app)
assert combined[0x6000:] == app and combined[:len(boot)] == boot
OUT.mkdir(exist_ok=False)
(OUT/'diagnostics').mkdir()
(OUT/'validation').mkdir()
for source, target in ((BUILD, 'App'), (ROOT/'bootloader/build', 'Bootloader')):
    stem = 'a300_firmware' if target == 'App' else 'bootloader'
    for ext in ('bin','elf','map','hex'):
        shutil.copy2(source/f'{stem}.{ext}', OUT/f'diagnostics/{target}-V3069.{ext}')
combined_path = OUT/'SWD-Combined-V3069.bin'
combined_path.write_bytes(combined)
subprocess.run([str(ROOT/'.toolchain/bin/arm-none-eabi-objcopy.exe'),
                '-I','binary','-O','ihex','--change-addresses','0x08000000',
                str(combined_path),str(OUT/'SWD-Combined-V3069.hex')],check=True)
subprocess.run([sys.executable,str(ROOT/'tools/gen_a300_ota_image.py'),
                '--input',str(OUT/'diagnostics/App-V3069.bin'),
                '--output',str(OUT/'A300-406-OTA-V3069.bin'),
                '--version-code','3069'],check=True)

# Independently decode every Intel HEX record and compare all flash bytes.
decoded = {}; base = 0; eof = False
for line in (OUT/'SWD-Combined-V3069.hex').read_text().splitlines():
    assert line.startswith(':') and not eof
    record=bytes.fromhex(line[1:]); length=record[0]
    assert len(record)==length+5 and sum(record)%256==0
    address=int.from_bytes(record[1:3],'big'); kind=record[3]; data=record[4:-1]
    if kind==0:
        for i,value in enumerate(data):
            at=base+address+i
            assert at not in decoded
            decoded[at]=value
    elif kind==4:
        assert length==2; base=int.from_bytes(data,'big')<<16
    elif kind==2:
        assert length==2; base=int.from_bytes(data,'big')<<4
    elif kind==1:
        assert length==0; eof=True
    elif kind in (3,5):
        assert length==4
    else:
        raise AssertionError(kind)
assert eof and len(decoded)==len(combined)
assert bytes(decoded[0x08000000+i] for i in range(len(combined)))==combined
ota_path=OUT/'A300-406-OTA-V3069.bin'; ota=ota_path.read_bytes()
assert struct.unpack('<IIIII12s',ota[:32]) == (
    0xA300B007,3069,len(app),zlib.crc32(app)&0xffffffff,0x41333030,bytes(12))
assert ota[32:]==app

shutil.copy2(ROOT/'release_identity.json',OUT/'release_identity.json')
for file in LOGS.iterdir():
    if file.is_file(): shutil.copy2(file,OUT/'validation'/file.name)
for name in ('flash-capacity.json','stack-analysis.json','stack-evidence.json','flash-build-profile.json'):
    shutil.copy2(BUILD/name,OUT/'validation'/name)
shutil.copy2(ROOT/'docs/nofix-0200-clock-20260920.md',OUT/'validation/nofix-clock-fix.md')
source_files=[]
for folder in ('src','include','bootloader/src','bootloader/include','bootloader/ldscript','ldscript','third_party/micro-ecc'):
    source_files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file())
source_files.extend(ROOT/p for p in ('Makefile','bootloader/Makefile','release_identity.json','tools/release_guard.py'))
source_files.extend((ROOT/'tools/tests').glob('test_*.py'))
source_hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(source_files))}
(OUT/'validation/source-sha256.json').write_text(json.dumps(source_hashes,indent=2)+'\n')
upload={'file':ota_path.name,'deviceModel':'A300-406','versionCode':3069,
        'versionName':identity['firmware_version'],'size':len(ota),
        'sha256':hashlib.sha256(ota).hexdigest(),'active':False,'mandatory':False,
        'signing':'platform-detached','releaseNotes':'HIL test: advance 0200 time while GNSS has no fix; preserve APN fix.'}
(OUT/'OTA-upload.json').write_text(json.dumps(upload,indent=2)+'\n')
readme=f'''# A300-406 V3.069 无定位时间修复验证包

版本：{identity['firmware_version']}；芯片 N32L406CBL7。
本包仅供用户实机/HIL 验证；硬件未验证，完整发布门禁未通过。

## 使用文件

- `SWD-Combined-V3069.hex`：推荐完整烧录文件，自带地址。
- `SWD-Combined-V3069.bin`：完整烧录 BIN，起始地址 `0x08000000`。
- `A300-406-OTA-V3069.bin`：OTA 平台上传文件；`deviceModel=A300-406`，
  `versionCode=3069`。平台按现有流程生成分离签名，设备通过 HTTP OTA 下载。
  元数据见 `OTA-upload.json`。本次未上传平台、未创建设备任务、未烧录。

完整 SWD 包首次启动会执行工厂初始化，清除配置及 OTA 授权/升级状态。
请先记录参数，烧录后恢复服务器和授权配置。OTA 只更新 App，保留设备参数，
不更新 Bootloader。不要将 SWD 合并文件或 diagnostics 中的裸 App 上传 OTA 平台。

若验证 OTA，请从 V3.068 或更低版本直接升到 V3.069；先烧录 V3.069 后再对同一设备
升级同版通常会被版本策略拒绝。不要修改版本头或跳过版本校验。

## 重点验收

1. 调试串口 115200、8N1，更新后确认 App 横幅为 V3.069。
2. 正常取得定位后进入休眠并唤醒，使保留快照建立；随后遮挡 GNSS，保持无定位。
3. 对照当前时间持续观察至少 10 分钟：新 0200 时间应随上报间隔推进，
   不再停留在失去定位前；坐标仍为可信历史位置，定位状态为未定位。
4. 覆盖 ACC 开关、浅休眠/唤醒及重新取得定位，确认无重复补时或时间跳回。
5. 断网产生盲区记录，恢复网络后核对补传保持原事件时间，新事件使用当前推进时间。

本次保留上一版 APN 配置确认和重复下发幂等修复。
冷启动尚无任何可信定位快照时，不新增伪造定位上报。
默认构建为浅休眠；STOP1 真实 RTC 补时仍需相应配置和硬件另行验证。

## 验证与限制

19 项定向回归通过；App/Bootloader 全量构建无编译警告。
平台签名信任锚、发布身份、Flash、Boot 静态容量及 libc 检查通过。
HEX 地址/校验和/内容、合并偏移、向量、工厂初始化记录、OTA 版本/产品/长度/CRC/载荷均核对通过。
App {len(app)} 字节，分区余量 {106496-len(app)} 字节，仍有 LOW_HEADROOM 提示。

完整 release-gate 实际退出 2：全程序栈/堆/中断证据不完整；未放宽任何门禁。
不能声称运行时 RAM 已验证安全、整机稳定或达到正式发布验收。
详细结果见 validation；文件哈希见 SHA256SUMS.txt。
'''
(OUT/'README.md').write_text(readme,encoding='utf-8')
files={p.relative_to(OUT).as_posix():{'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
       for p in sorted(OUT.rglob('*')) if p.is_file()}
manifest={'version':identity['firmware_version'],'versionCode':3069,'release_approved':False,
          'hardware_verified':False,'release_gate_exit':2,
          'release_gate_reason':'Incomplete whole-program stack/heap/IRQ evidence',
          'ota_updates_bootloader':False,'swd_factory_initializes':True,
          'app_bytes':len(app),'boot_bytes':len(boot),'package_validation':'passed',
          'files':files}
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
files['manifest.json']={'sha256':hashlib.sha256((OUT/'manifest.json').read_bytes()).hexdigest()}
(OUT/'SHA256SUMS.txt').write_text(''.join(f"{v['sha256']}  {k}\n" for k,v in sorted(files.items())),encoding='utf-8')
archive=OUT.parent/(OUT.name+'.zip')
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(OUT.rglob('*')):
        if p.is_file(): z.write(p,OUT.name+'/'+p.relative_to(OUT).as_posix())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for p in OUT.rglob('*'):
        if p.is_file(): assert z.read(OUT.name+'/'+p.relative_to(OUT).as_posix())==p.read_bytes()
print('HIL package validated:',OUT)
print('ZIP SHA256:',hashlib.sha256(archive.read_bytes()).hexdigest())
