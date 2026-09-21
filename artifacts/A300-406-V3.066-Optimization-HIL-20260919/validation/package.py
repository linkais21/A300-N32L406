from pathlib import Path
import difflib, hashlib, json, shutil, struct, subprocess, sys, zipfile, zlib
WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
OUT = ROOT / 'artifacts/A300-406-V3.066-Optimization-HIL-20260919'
APP = WORK / 'app'
BOOT = WORK / 'source/bootloader/build'
sys.path.insert(0, str(ROOT / 'tools'))
from build_dev_release import build_combined, validate_app_vectors

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

hashes = json.loads((WORK / 'source-hashes.json').read_text())
for n, h in hashes.items():
    assert sha(ROOT / n) == h and sha(WORK / 'source' / n) == h, n
records = {p.name.removesuffix('.command.json'): json.loads(p.read_text()) for p in WORK.glob('*.command.json')}
required = ['build', 'boot-build', 'release-gate', 'platform-trust-guard', 'frame-budget', 'libc-parser', 'boot-ram', 'diff-check']
assert all(n in records for n in required)
assert len(records) == 46, len(records)
for n, r in records.items():
    assert r['exit_code'] == (2 if n == 'release-gate' else 0), (n, r)
for n in ['build', 'boot-build']:
    assert b'warning:' not in (WORK / (n + '.log')).read_bytes().lower()
gate = (WORK / 'release-gate.log').read_text(encoding='utf-8', errors='replace')
assert 'release-guard: PASS' in gate and 'incomplete stack evidence' in gate
identity = json.loads((ROOT / 'release_identity.json').read_text())
assert identity['firmware_version_counter'] == 3066
app = (APP / 'a300_firmware.bin').read_bytes()
boot = (BOOT / 'bootloader.bin').read_bytes()
assert identity['firmware_version'].encode() in app
assert b'V3.065' not in app
validate_app_vectors(app)
cap = json.loads((APP / 'flash-capacity.json').read_text())
assert cap['status'] == 'passed' and cap['bin_sha256'] == sha(APP / 'a300_firmware.bin')
assert cap['remaining_bytes'] >= 1024
stack = json.loads((APP / 'stack-analysis.json').read_text())
assert stack['status'] == 'incomplete' and stack['elf_sha256'] == sha(APP / 'a300_firmware.elf')
combined = build_combined(boot, app)
assert len(combined) <= 131072
OUT.mkdir(exist_ok=False)
objcopy = ROOT / '.toolchain/bin/arm-none-eabi-objcopy.exe'
for label, body, origin in [('App', app, 0x08006000), ('Bootloader', boot, 0x08000000), ('SWD-Combined', combined, 0x08000000)]:
    p = OUT / (label + '-V3066.bin')
    p.write_bytes(body)
    h = p.with_suffix('.hex')
    subprocess.run([str(objcopy), '-I', 'binary', '-O', 'ihex', '--change-addresses', hex(origin), str(p), str(h)], check=True)
    verify = WORK / (label + '-hex-check.bin')
    subprocess.run([str(objcopy), '-I', 'ihex', '-O', 'binary', str(h), str(verify)], check=True)
    assert verify.read_bytes() == body
for folder, stem, label in [(APP, 'a300_firmware', 'App'), (BOOT, 'bootloader', 'Bootloader')]:
    for ext in ['elf', 'map']:
        shutil.copy2(folder / (stem + '.' + ext), OUT / (label + '-V3066.' + ext))
ota = OUT / 'A300-406-OTA-V3066.bin'
subprocess.run([sys.executable, str(ROOT / 'tools/gen_a300_ota_image.py'), '--input', str(OUT / 'App-V3066.bin'), '--output', str(ota), '--version-code', '3066'], check=True)
wire = ota.read_bytes()
assert struct.unpack_from('<5I12s', wire) == (0xA300B007, 3066, len(app), zlib.crc32(app) & 0xffffffff, 0x41333030, bytes(12))
assert wire[32:] == app
patch = ''
for p in (WORK / 'before').rglob('*'):
    if p.is_file():
        n = p.relative_to(WORK / 'before').as_posix()
        patch += ''.join(difflib.unified_diff(p.read_text(encoding='utf-8').splitlines(True), (ROOT / n).read_text(encoding='utf-8').splitlines(True), fromfile='before/' + n, tofile='after/' + n))
(WORK / 'version.patch').write_text(patch, encoding='utf-8')
valid = OUT / 'validation'
valid.mkdir()
for p in WORK.iterdir():
    if p.is_file() and p.suffix in ['.log', '.json', '.patch', '.py']:
        shutil.copy2(p, valid / p.name)
for n in ['flash-capacity.json', 'stack-analysis.json', 'stack-evidence.json', 'flash-build-profile.json']:
    shutil.copy2(APP / n, valid / n)
shutil.copy2(ROOT / 'release_identity.json', OUT / 'release_identity.json')
upload = dict(file=ota.name, deviceModel='A300-406', versionCode=3066, versionName=identity['firmware_version'], size=len(wire), sha256=sha(ota), active=False, mandatory=False, signing='platform-detached', releaseNotes='HIL candidate: shared default configuration and session-send bookkeeping; 1064-byte App headroom. Incomplete RAM release evidence.')
(OUT / 'OTA-upload.json').write_text(json.dumps(upload, indent=2) + '\n')
manifest = dict(version=identity['firmware_version'], versionCode=3066, release_approved=False, hardware_verified=False, release_gate_exit=2, release_gate_reason='Incomplete whole-program stack/heap/IRQ evidence', app_bytes=len(app), ota_bytes=len(wire), flash_remaining=cap['remaining_bytes'], host_test_scripts_passed=38, files={p.name: dict(size=p.stat().st_size, sha256=sha(p)) for p in OUT.iterdir() if p.is_file()})
(OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
readme = f'''# A300-406 V3.066 优化实机验证候选包

版本：{identity['firmware_version']}，versionCode=3066，deviceModel=A300-406。

## 使用文件

- 现有设备 OTA 升级：`A300-406-OTA-V3066.bin`。上传平台后由平台签名；上传参数见 OTA-upload.json。
- SWD 整包：`SWD-Combined-V3066.hex`，或 BIN 起始地址 0x08000000。
- SWD 合并包包含首次启动工厂初始化请求，会触发工厂初始化；保留现有配置请使用 OTA 文件。
- 单独 App BIN 地址 0x08006000，不能作为平台 OTA 上传文件。

## 变化

集成第十轮优化：共用默认配置初始化及注册/鉴权发送记账逻辑。相对 V3.065 原包净省 1024 B；现有功能、日志、默认值、协议和 Flash 布局保持不变。本轮仅更新版本身份及对应守卫摘要，未修改业务代码。

App 为 {len(app)} B，104 KiB 分区剩余 {cap['remaining_bytes']} B；OTA 文件 {len(wire)} B（包含 32 B 头）。静态 SRAM 17720 B。

## 已自动验证与限制

38 个 host 测试脚本通过；App/Boot 构建无编译警告；版本身份、平台信任锚、Flash 容量、Boot RAM、必要帧预算、libc parser 及版本文件 diff-check 通过。OTA 头/CRC/版本/包体、HEX 回读、ZIP CRC、SHA256 清单已核对。完整命令和输入哈希见 validation，源码快照保存在本地 build/optimization-v3066-20260919/source。

完整 release-gate 退出 2，首个阻断为 RAM 栈证据不完整，详见 validation/release-gate.log；未降低门禁。剩余空间低于 4 KiB 告警阈值。本包仅供实机/HIL 验证，不代表量产发布通过；本轮未烧录、上传或部署。

## 需要实机/HIL 验证

1. OTA 从当前版本升级后启动横幅和平台版本为 V3.066，健康确认及 success 上报正常。
2. 原有配置保留，首次默认配置、旧配置启动迁移正常。
3. 主备平台注册/鉴权、断网重连及 SEND OK 超时后迟到 ACK 正常。
4. 定位/静止锁点、盲区补传、ACC/休眠唤醒及继电器安全控制无回归。

文件校验值见 SHA256SUMS.txt。保留完整串口测试日志用于比较。
'''
(OUT / 'README.md').write_text(readme, encoding='utf-8')
(ROOT / 'docs/optimization-v3066-delivery-20260919.md').write_text(readme, encoding='utf-8')
files = sorted(p for p in OUT.rglob('*') if p.is_file())
(OUT / 'SHA256SUMS.txt').write_text(''.join(sha(p) + '  ' + p.relative_to(OUT).as_posix() + '\n' for p in files))
archive = OUT.parent / (OUT.name + '.zip')
with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
    for p in OUT.rglob('*'):
        if p.is_file(): z.write(p, OUT.name + '/' + p.relative_to(OUT).as_posix())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert z.read(OUT.name + '/' + ota.name) == wire
archive.with_suffix('.zip.sha256').write_text(sha(archive) + '  ' + archive.name + '\n')
print(json.dumps(manifest, indent=2))
