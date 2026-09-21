"""Assemble user-requested V3.070 hardware-validation artifacts, without release approval."""
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

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_dev_release import build_combined, validate_app_vectors, validate_factory_init_marker

LOGS = ROOT / 'build-v3070-functional-validation'
BUILD = ROOT / 'build-v3070-functional'
OUT = ROOT / 'artifacts/A300-406-V3.070-Functional-HIL-20260920'
OBJCOPY = Path('D:/A300_Tools/toolchains/arm-gnu-toolchain-14.3.rel1/bin/arm-none-eabi-objcopy.exe')
identity = json.loads((ROOT / 'release_identity.json').read_text(encoding='utf-8'))
assert identity['firmware_version_counter'] == 3070
for component in ('app', 'boot'):
    assert json.loads((LOGS / f'{component}-build-command.json').read_text())['exit_code'] == 0
    assert not re.search(r'warning:|error:', (LOGS / f'{component}-build.log').read_text(), re.I)
gates = json.loads((LOGS / 'gates.json').read_text())
assert [g['exit_code'] for g in gates] == [2, 0, 0, 0]
assert 'release-guard: PASS' in (LOGS / 'release-gate.log').read_text()
assert 'incomplete stack evidence' in (LOGS / 'release-gate.log').read_text()

app = (BUILD / 'a300_firmware.bin').read_bytes()
boot = (ROOT / 'bootloader/build/bootloader.bin').read_bytes()
assert identity['firmware_version'].encode() in app
validate_app_vectors(app)
validate_factory_init_marker(boot)
combined = build_combined(boot, app)
assert combined[0x6000:] == app and combined[:len(boot)] == boot
assert len(combined) <= 128 * 1024

# Verify the embedded public key against captured platform signing metadata.
# This checks package compatibility, without contacting a server or using a private key.
key_text = (ROOT / 'include/trusted_public_key.h').read_text()
key_body = re.search(r'trusted_public_key\[[^\]]+\]\s*=\s*\{([^}]+)\}', key_text).group(1)
key = bytes(int(v, 16) for v in re.findall(r'0x([0-9a-fA-F]{2})', key_body))
assert len(key) == 64 and key in app and key in boot
fixture = json.loads((ROOT / 'tools/tests/fixtures/platform_v3035_signature.json').read_text())
assert fixture['signingKeyId'] == int(re.search(r'#define TRUSTED_SIGNING_KEY_ID (\d+)', key_text).group(1))
public = ec.EllipticCurvePublicNumbers(int.from_bytes(key[:32], 'big'), int.from_bytes(key[32:], 'big'), ec.SECP256R1()).public_key()
signature = bytes.fromhex(fixture['signature'])
public.verify(utils.encode_dss_signature(int.from_bytes(signature[:32], 'big'), int.from_bytes(signature[32:], 'big')),
              bytes.fromhex(fixture['sha256']), ec.ECDSA(utils.Prehashed(hashes.SHA256())))

OUT.mkdir(exist_ok=False)
(OUT / 'diagnostics').mkdir()
(OUT / 'validation').mkdir()
for source, target in ((BUILD, 'App'), (ROOT / 'bootloader/build', 'Bootloader')):
    stem = 'a300_firmware' if target == 'App' else 'bootloader'
    for ext in ('bin', 'elf', 'map', 'hex'):
        shutil.copy2(source / f'{stem}.{ext}', OUT / f'diagnostics/{target}-V3070.{ext}')
combined_path = OUT / 'SWD-Combined-V3070.bin'
combined_path.write_bytes(combined)
subprocess.run([str(OBJCOPY), '-I', 'binary', '-O', 'ihex', '--change-addresses', '0x08000000',
                str(combined_path), str(OUT / 'SWD-Combined-V3070.hex')], check=True)
ota_path = OUT / 'A300-406-OTA-V3070.bin'
subprocess.run([sys.executable, str(ROOT / 'tools/gen_a300_ota_image.py'), '--input',
                str(OUT / 'diagnostics/App-V3070.bin'), '--output', str(ota_path), '--version-code', '3070'], check=True)

# Independently decode address records and check every delivered flash byte.
decoded = {}
base = 0
eof = False
for line in (OUT / 'SWD-Combined-V3070.hex').read_text().splitlines():
    assert line.startswith(':') and not eof
    record = bytes.fromhex(line[1:])
    length = record[0]
    assert len(record) == length + 5 and sum(record) % 256 == 0
    address = int.from_bytes(record[1:3], 'big')
    kind = record[3]
    data = record[4:-1]
    if kind == 0:
        for i, value in enumerate(data):
            at = base + address + i
            assert at not in decoded
            decoded[at] = value
    elif kind == 4:
        assert length == 2
        base = int.from_bytes(data, 'big') << 16
    elif kind == 2:
        assert length == 2
        base = int.from_bytes(data, 'big') << 4
    elif kind == 1:
        assert length == 0
        eof = True
    elif kind in (3, 5):
        assert length == 4
    else:
        raise AssertionError(kind)
assert eof and len(decoded) == len(combined)
assert bytes(decoded[0x08000000 + i] for i in range(len(combined))) == combined
ota = ota_path.read_bytes()
assert struct.unpack('<IIIII12s', ota[:32]) == (
    0xA300B007, 3070, len(app), zlib.crc32(app) & 0xffffffff, 0x41333030, bytes(12))
assert ota[32:] == app

shutil.copy2(ROOT / 'release_identity.json', OUT / 'release_identity.json')
for file in LOGS.iterdir():
    if file.is_file():
        shutil.copy2(file, OUT / 'validation' / file.name)
for name in ('flash-capacity.json', 'stack-analysis.json', 'stack-evidence.json', 'flash-build-profile.json'):
    shutil.copy2(BUILD / name, OUT / 'validation' / name)
shutil.copy2(ROOT / 'docs/functional-repair-20260920.md', OUT / '功能修改说明.md')
shutil.copy2(ROOT / 'build-functional-repair-20260920/platform-acceptance.json', OUT / 'validation/platform-acceptance.json')

source_files = []
for folder in ('src', 'include', 'bootloader/src', 'bootloader/include', 'bootloader/ldscript', 'ldscript', 'third_party/micro-ecc',
               'sdk/Nations.N32L40x_Library.2.2.0/firmware'):
    source_files.extend(p for p in (ROOT / folder).rglob('*') if p.is_file() and p.suffix.lower() in ('.c', '.h', '.s', '.ld'))
source_files.extend(ROOT / p for p in ('Makefile', 'bootloader/Makefile', 'release_identity.json', 'tools/release_guard.py', 'tools/gen_a300_ota_image.py'))
source_hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(source_files))}
(OUT / 'validation/source-sha256.json').write_text(json.dumps(source_hashes, indent=2) + '\n')
upload = {'file': ota_path.name, 'deviceModel': 'A300-406', 'versionCode': 3070,
          'versionName': identity['firmware_version'], 'size': len(ota), 'sha256': hashlib.sha256(ota).hexdigest(),
          'active': False, 'mandatory': False, 'signing': 'platform-detached',
          'releaseNotes': 'Hardware validation: text query replies, heartbeat recovery, no-fix reports, OTA retry, blind storage and corner reporting.'}
(OUT / 'OTA-upload.json').write_text(json.dumps(upload, indent=2) + '\n')
readme = f'''# A300-406 V3.070 实机验证包

版本：{identity['firmware_version']}，OTA 版本号 3070，MCU 为 N32L406CBL7。
本包包含本轮功能修复；尚未实机验收，RAM 完整峰值证据不完整，正式发布门禁未通过。

## 使用文件

- `SWD-Combined-V3070.hex`：完整烧录文件，推荐使用，自带地址。
- `SWD-Combined-V3070.bin`：同内容 BIN，起始烧录地址 `0x08000000`。
- `A300-406-OTA-V3070.bin`：上传 OTA 平台的升级文件，型号 `A300-406`，版本号 `3070`。元数据见 `OTA-upload.json`。
- `diagnostics`：用于核对的 App、Bootloader、ELF 和 map，不要将裸 App 或合并烧录文件作为 OTA 上传包。

**完整 SWD 烧录后首次启动会执行工厂初始化，清除设备配置及 OTA 授权/升级状态。请先记录参数，烧录后恢复服务器和授权配置。**
OTA 只更新 App，保留设备参数，不更新 Bootloader。上传后由现有平台生成分离签名，设备按 HTTP OTA 流程下载。
从 V3.069 或更低版本验证升级到 V3.070；先烧录 V3.070 后再升级同版通常会被版本策略拒绝。
本次没有烧录、上传平台、创建设备升级任务或部署服务。

## 实际功能验收

先确认 115200/8N1 串口启动版本为 V3.070，再验证：

1. SMS 任意号码仍可操作；0x8300 下发 PARAM#、HBT# 后，本地平台能收到 0x0301 参数文本。
2. 从未定位时有未定位状态报告；恢复卫星信号后正常定位。静止漂移过滤、AGNSS 和常规上报继续验证。
3. 平台停止回复心跳时，设备超时断开并恢复连接；正常运行至少 24 小时无死机、异常反复重连。
4. 日志接收和多参数设置、0x8103/0x8104/0x8106 参数业务、0x8105 支持的控制、0x8107 属性查询符合预期。
5. ACC/Gsensor 唤醒休眠、普通弯/缓弯/连续弯行车轨迹符合预期。
6. OTA 正常升级及断网/断电恢复后最终升级成功；断网期间盲区保存，恢复后完整补报。

本地 test-platform 已在源码中补上 0x0704 接收和 0x0301 中文兼容；正在运行的旧平台进程不会自动获得这些修改，本次未重启服务。完整修改范围见《功能修改说明.md》。

## 生成检查结果

App/Bootloader 编译无警告；App {len(app)} 字节，App 分区余量 {106496-len(app)} 字节。
版本一致性、Flash 容量、Boot 静态容量、HEX 地址/校验和/内容、合并偏移、向量、工厂初始化记录、OTA 版本/产品/长度/CRC/载荷一致性均通过。
App 与 Bootloader 中包含同一公钥，已用留存的平台签名元数据核对；这不是本包已在线签名或设备升级成功的证据。

完整 release-gate 退出 2：RAM 全程序栈/堆/中断峰值证据不完整。
静态 RAM 17264 字节，已知主调用链栈 2624 字节，不能保证运行时 RAM 不溢出。
首次版本检查因版本更新后的指纹未同步而失败；逐项确认仅版本/时间变化后同步指纹，版本检查通过，RAM 门禁仍保持失败。
所有实机行为需要实机/HIL 验证。文件哈希见 SHA256SUMS.txt，构建与门禁记录见 validation。
'''
(OUT / 'README.md').write_text(readme, encoding='utf-8')
files = {p.relative_to(OUT).as_posix(): {'size': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
         for p in sorted(OUT.rglob('*')) if p.is_file()}
manifest = {'version': identity['firmware_version'], 'versionCode': 3070, 'release_approved': False,
            'hardware_verified': False, 'release_gate_exit': 2,
            'release_gate_reason': 'Incomplete whole-program stack/heap/IRQ evidence',
            'ota_updates_bootloader': False, 'swd_factory_initializes': True,
            'app_bytes': len(app), 'boot_bytes': len(boot), 'package_validation': 'passed', 'files': files}
(OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
files['manifest.json'] = {'sha256': hashlib.sha256((OUT / 'manifest.json').read_bytes()).hexdigest()}
(OUT / 'SHA256SUMS.txt').write_text(''.join(f"{v['sha256']}  {k}\n" for k, v in sorted(files.items())), encoding='utf-8')
archive = OUT.parent / (OUT.name + '.zip')
with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
    for p in sorted(OUT.rglob('*')):
        if p.is_file():
            z.write(p, OUT.name + '/' + p.relative_to(OUT).as_posix())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for p in OUT.rglob('*'):
        if p.is_file():
            assert z.read(OUT.name + '/' + p.relative_to(OUT).as_posix()) == p.read_bytes()
print('HIL package validated:', OUT)
print('ZIP SHA256:', hashlib.sha256(archive.read_bytes()).hexdigest())
