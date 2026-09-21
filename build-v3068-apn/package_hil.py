"""Assemble the explicitly requested V3.068 HIL artifacts, not a release approval."""
from pathlib import Path
import hashlib, json, re, shutil, struct, subprocess, sys, zipfile, zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_dev_release import build_combined, validate_app_vectors, validate_factory_init_marker
from tools.gen_a300_ota_image import HEADER, MAGIC, PRODUCT_ID

BUILD = ROOT / 'build-v3068-apn'
BOOT = ROOT / 'bootloader/build'
OUT = ROOT / 'artifacts/A300-406-V3.068-APN-Fix-HIL-20260920'
ZIP = OUT.parent / (OUT.name + '.zip')
assert not OUT.exists() and not ZIP.exists(), 'Never overwrite an existing delivery'
identity = json.loads((ROOT / 'release_identity.json').read_text(encoding='utf-8'))
assert identity['firmware_version_counter'] == 3068
version = identity['firmware_version']
app = (BUILD / 'a300_firmware.bin').read_bytes()
boot = (BOOT / 'bootloader.bin').read_bytes()
assert version.encode() in app
assert b'start\0' in boot
validate_factory_init_marker(boot)
validate_app_vectors(app)
combined = build_combined(boot, app)
flash = json.loads((BUILD / 'flash-capacity.json').read_text())
sha = lambda data: hashlib.sha256(data).hexdigest()
assert flash['bin_sha256'] == sha(app) and flash['status'] == 'passed'
for name in ['build-v3068-apn.log', 'build-v3068-boot.log']:
    assert not re.search(r'warning:', (ROOT / name).read_text(encoding='utf-8'), re.I)
gate_log = (ROOT / 'build-v3068-gates.log').read_text(encoding='utf-8')
assert 'release-guard: PASS' in gate_log
assert 'incomplete stack evidence' in gate_log

# Record source identity without including private keys or runtime configuration.
inputs = [ROOT / 'Makefile', ROOT / 'release_identity.json']
for directory, pattern in [('src','*.c'), ('include','*.h'), ('ldscript','*.ld'),
                           ('bootloader/src','*'), ('bootloader/include','*.h'),
                           ('bootloader/ldscript','*.ld')]:
    inputs.extend(p for p in (ROOT / directory).glob(pattern) if p.is_file())
for p in inputs:
    if p.suffix in ['.c', '.h', '.s', '.ld']:
        target = BOOT / 'bootloader.elf' if 'bootloader' in p.relative_to(ROOT).parts else BUILD / 'a300_firmware.elf'
        assert p.stat().st_mtime_ns <= target.stat().st_mtime_ns, f'Input changed after build: {p.name}'

OUT.mkdir()
(OUT / 'diagnostics').mkdir()
(OUT / 'validation').mkdir()
(OUT / 'SWD-Combined-V3068.bin').write_bytes(combined)

def record(address, kind, data):
    raw = bytes([len(data), address >> 8, address & 255, kind]) + data
    return ':' + (raw + bytes([-sum(raw) & 255])).hex().upper()

lines = []
upper = None
for i in range(0, len(combined), 16):
    address = 0x08000000 + i
    if address >> 16 != upper:
        upper = address >> 16
        lines.append(record(0, 4, upper.to_bytes(2, 'big')))
    lines.append(record(address & 65535, 0, combined[i:i+16]))
lines.append(record(0, 1, b''))
(OUT / 'SWD-Combined-V3068.hex').write_text('\n'.join(lines)+'\n', encoding='ascii')
ota = OUT / 'A300-406-OTA-V3068.bin'
subprocess.run([sys.executable, str(ROOT / 'tools/gen_a300_ota_image.py'),
                '--input', str(BUILD / 'a300_firmware.bin'), '--output', str(ota),
                '--version-code', '3068'], check=True)
for source, target in [(BUILD/'a300_firmware.bin','App-V3068.bin'),
                       (BUILD/'a300_firmware.elf','App-V3068.elf'),
                       (BUILD/'a300_firmware.map','App-V3068.map'),
                       (BOOT/'bootloader.bin','Bootloader-V3068.bin'),
                       (BOOT/'bootloader.elf','Bootloader-V3068.elf'),
                       (BOOT/'bootloader.map','Bootloader-V3068.map')]:
    shutil.copy2(source, OUT/'diagnostics'/target)
for source in [BUILD/'flash-capacity.json', BUILD/'stack-analysis.json', BUILD/'stack-evidence.json',
               ROOT/'build-v3068-apn.log',ROOT/'build-v3068-boot.log',ROOT/'build-v3068-gates.log',
               ROOT/'build-v3068-tests.json']:
    shutil.copy2(source, OUT/'validation'/source.name)

# Preserve the initial version-hash failure and record its corrected rerun.
reruns=[]
for command in [[sys.executable,'tools/tests/test_release_identity_contract.py'],
                [sys.executable,'tools/map_ram_guard.py','bootloader','bootloader/build/bootloader.map']]:
    r=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
    assert r.returncode==0, r.stdout+r.stderr
    reruns.append(dict(command=command[1:],exit_code=r.returncode,output=r.stdout+r.stderr))
(OUT/'validation/final-reruns.json').write_text(json.dumps(reruns,indent=2)+'\n',encoding='utf-8')
(OUT/'validation/source-sha256.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in inputs},indent=2)+'\n',encoding='utf-8')
shutil.copy2(ROOT/'release_identity.json',OUT/'release_identity.json')
shutil.copy2(ROOT/'docs/apn-config-ack-fix-20260920.md',OUT/'validation/APN-fix.md')
upload = dict(file=ota.name, deviceModel='A300-406', versionCode=3068, versionName=version,
              size=ota.stat().st_size, sha256=sha(ota.read_bytes()), active=False, mandatory=False,
              signing='platform-detached', releaseNotes='实机验证版：修复 APN 配置确认失败及重复下发导致每分钟重连。')
(OUT/'OTA-upload.json').write_text(json.dumps(upload,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
(OUT/'README.md').write_text(f'''# A300-406 V3.068 APN 修复实机验证包

版本：{version}；MCU：N32L406CBL7；OTA versionCode：3068。

## 使用文件

- 完整 SWD 烧录：`SWD-Combined-V3068.hex`（推荐，文件自带地址）。
- 完整 SWD BIN：`SWD-Combined-V3068.bin`，起始地址 `0x08000000`。
- 平台 OTA 上传：`A300-406-OTA-V3068.bin`，deviceModel=`A300-406`，versionCode=`3068`。
- `OTA-upload.json` 提供上传参数。OTA 文件沿用平台分离签名格式，上传后由现有平台签名；本地未上传或签名本包。

**完整 SWD 包首次启动会执行工厂初始化，清除设备配置及 OTA 授权/升级状态。请先记录需要恢复的参数。OTA 仅更新 App，保留现有配置，不更新 Bootloader。禁止把完整 SWD BIN 当作 OTA 包上传。**

## 修复与验收

配置保存成功后先发执行确认，再应用网络重建。相同 APN 参数重复下发不再重启 PDP；实际 APN/用户名/密码变化仍正常生效。配置或持久化失败不确认成功，确认发送失败可在后续平台重发时重试。

本次重建当前工作树，保留已有用户改动；本轮业务源码改动仅涉及 `cfg_query.c` 和 `f39_config_adapter.c`。额外同步版本身份、身份测试及审核摘要。未提交、烧录、上传平台或部署。

App/Boot 编译无 warning。App Flash 使用 {len(app)} / 106496 字节，剩余 {106496-len(app)} 字节；保留 LOW_HEADROOM 提示。配置、UDP、OTA 格式、平台签名信任链、Flash 布局和 Boot 恢复相关 28 项脚本最终通过。版本身份测试首次因旧版本审核摘要失败，同步 V3.068 摘要后重跑通过，原始记录与重跑记录均保留。

**完整发布门禁未通过：RAM/栈证据 incomplete，不能证明整程序栈/堆/中断峰值安全。此包仅供实机/HIL 验证，不是已完成发布验收的正式包。** Boot 静态容量检查通过，不代表运行栈已经审计。

需要实机/HIL：升级后确认 App 为 V3.068，平台 `APN,AUTO#` 任务转为配置成功，至少观察 5 个一分钟查询周期无周期重连；再检查心跳、定位、双通道通信和栈水位。真实 APN 变更应恢复联网，重复相同参数不再重连。设备已是 3068 时，同版本 OTA 可能按现有版本策略不再提供更新。

`validation/` 保存测试、门禁和输入摘要；`diagnostics/` 保存分析文件。文件哈希见 `SHA256SUMS.txt`。
''',encoding='utf-8')

# Independent byte-level verification: OTA header/body and Intel HEX checksums/addresses.
payload = ota.read_bytes()
magic, code, length, crc, product, reserved = HEADER.unpack_from(payload)
assert (magic,code,length,crc,product,reserved)==(MAGIC,3068,len(app),zlib.crc32(app)&0xffffffff,PRODUCT_ID,bytes(12))
assert payload[HEADER.size:] == app == combined[0x6000:]
address_base=0
decoded={}
for line in (OUT/'SWD-Combined-V3068.hex').read_text().splitlines():
    raw=bytes.fromhex(line[1:]); assert sum(raw)&255==0 and len(raw)==raw[0]+5
    address=int.from_bytes(raw[1:3],'big'); data=raw[4:-1]
    if raw[3]==4: address_base=int.from_bytes(data,'big')<<16
    elif raw[3]==0:
        for i,b in enumerate(data):
            key=address_base+address+i
            assert key not in decoded
            decoded[key]=b
    else: assert raw[3]==1 and not data
assert min(decoded)==0x08000000 and len(decoded)==len(combined)
assert bytes(decoded[0x08000000+i] for i in range(len(combined)))==combined
assert combined[:len(boot)]==boot
assert all(b==255 for b in combined[len(boot):0x6000])
validate_factory_init_marker(combined)
validate_app_vectors(combined,0x6000)
tests=json.loads((ROOT/'build-v3068-tests.json').read_text())
assert len(tests)==28 and all(t['exit_code']==0 or t['test']=='release_identity_contract' for t in tests)
manifest=dict(version=version,versionCode=3068,release_approved=False,hardware_verified=False,
              release_gate_exit=2,release_gate_reason='Incomplete whole-program stack/heap/IRQ evidence',
              ota_updates_bootloader=False,swd_factory_initializes=True,app_bytes=len(app),boot_bytes=len(boot),
              app_sha256=sha(app),boot_sha256=sha(boot),package_validation='passed',
              files={p.relative_to(OUT).as_posix():dict(size=p.stat().st_size,sha256=sha(p.read_bytes())) for p in sorted(OUT.rglob('*')) if p.is_file()})
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
(OUT/'SHA256SUMS.txt').write_text(''.join(f'{sha(p.read_bytes())}  {p.relative_to(OUT).as_posix()}\n' for p in sorted(OUT.rglob('*')) if p.is_file()),encoding='utf-8')
with zipfile.ZipFile(ZIP,'x',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(OUT.rglob('*')):
        if p.is_file(): z.write(p,OUT.name+'/'+p.relative_to(OUT).as_posix())
with zipfile.ZipFile(ZIP) as z:
    assert z.testzip() is None
    for p in OUT.rglob('*'):
        if p.is_file(): assert z.read(OUT.name+'/'+p.relative_to(OUT).as_posix())==p.read_bytes()
print(json.dumps(dict(directory=str(OUT),zip=str(ZIP),zip_sha256=sha(ZIP.read_bytes()),
                     app_bytes=len(app),ota_bytes=len(payload),combined_bytes=len(combined)),indent=2))
