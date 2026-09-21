from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_dev_release import build_combined, validate_app_vectors, validate_factory_init_marker

BUILD = Path(__file__).resolve().parent
OUT = ROOT / 'artifacts/A300-406-V3.057-Optimization-HIL-20260918'
identity = json.loads((ROOT / 'release_identity.json').read_text())
hashes = json.loads((BUILD / 'source-hashes-final.json').read_text())
assert all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in hashes.items())
records = json.loads((BUILD / 'commands.json').read_text())
assert len([r for r in records if r['label'].startswith('test_')]) == 34
assert all(r['exit_code'] == 0 for r in records if r['label'].startswith('test_') and r['label'] != 'test_flash_gate_build')
assert json.loads((BUILD / 'fixture-fix-validation.json').read_text())['exit_code'] == 0
for name in ('app-build', 'boot-build-fixed'):
    assert not re.search(r'\bwarning:', (BUILD / (name + '.log')).read_text(), re.I)
assert next(r for r in records if r['label'] == 'release-gate')['exit_code'] != 0

OUT.mkdir(exist_ok=False)
for role, stem in (('App', 'a300_firmware'), ('Bootloader', 'bootloader')):
    source = BUILD / ('app' if role == 'App' else 'boot')
    for suffix in ('.bin', '.hex', '.elf', '.map'):
        shutil.copy2(source / (stem + suffix), OUT / (role + '-N32L406CBL7' + suffix))
app = (OUT / 'App-N32L406CBL7.bin').read_bytes()
boot = (OUT / 'Bootloader-N32L406CBL7.bin').read_bytes()
assert identity['firmware_version'].encode() in app
assert len(app) <= 106496
combined = build_combined(boot, app)
(OUT / 'Combined-N32L406CBL7.bin').write_bytes(combined)
objcopy = ROOT / '.toolchain/bin/arm-none-eabi-objcopy.exe'
subprocess.run([str(objcopy), '-I', 'binary', '-O', 'ihex', '--change-addresses', '0x08000000',
                str(OUT / 'Combined-N32L406CBL7.bin'), str(OUT / 'Combined-N32L406CBL7.hex')], check=True)
for role in ('App', 'Bootloader', 'Combined'):
    roundtrip = BUILD / (role + '-hex-roundtrip.bin')
    subprocess.run([str(objcopy), '-I', 'ihex', '-O', 'binary',
                    str(OUT / (role + '-N32L406CBL7.hex')), str(roundtrip)], check=True)
    assert roundtrip.read_bytes() == (OUT / (role + '-N32L406CBL7.bin')).read_bytes()
assert combined[0x6000:] == app
validate_factory_init_marker(combined)
validate_app_vectors(combined, 0x6000)

for p in hashes:
    target = OUT / 'source' / p
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / p, target)
validation = OUT / 'validation'
validation.mkdir()
for p in BUILD.iterdir():
    if p.is_file() and p.suffix in ('.log', '.json', '.py', '.mk'):
        shutil.copy2(p, validation / p.name)
for p in (BUILD / 'app').rglob('*'):
    if p.is_file() and p.suffix in ('.su', '.json'):
        target = validation / 'app' / p.relative_to(BUILD / 'app')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
for suffix in ('.elf', '.map'):
    shutil.copy2(BUILD / 'app' / ('a300_firmware' + suffix), validation / 'app' / ('a300_firmware' + suffix))
shutil.copy2(ROOT / 'release_identity.json', OUT / 'release_identity.json')
shutil.copy2(BUILD / 'app/flash-capacity.json', OUT / 'flash-capacity.json')
shutil.copy2(ROOT / 'docs/optimization-v3057-20260918.md', OUT / 'CHANGELOG.md')
(OUT / 'README.md').write_text(f'''# V3.057 优化整合 HIL 测试包

版本：{identity['firmware_version']}，计数器 3057。

合入高频日志分级与 libc exit/stdio 清理链移除；保持内联阈值 64 和坐标/非坐标精度策略。
App 106160 B，Flash 余 336 B；静态 RAM 17756 B。

**仅供专用测试设备：release_approved=false。完整 release-gate 因全程序栈证据不完整失败，需要实机/HIL 验证。**
34 个相关主机测试脚本最终通过。全部初始失败、修复后结果及门禁日志见 validation；具体合入范围见 CHANGELOG.md。

烧录文件：Combined-N32L406CBL7.hex 自带地址。BIN 地址：Combined/Bootloader 为 0x08000000，App 为 0x08006000。
**完整烧录 Combined/Bootloader 将触发既有出厂初始化，清除配置、BCR、OTA 断点及授权记录。先保存参数，烧录后需重新配置。**
本次未烧录、未部署；不含 OTA 平台上传包。不要将原始 App BIN 直接用于平台上传。

确认启动显示 V3.057，验证入网/定位/命令回复、里程、AGNSS/OTA、ACC 休眠唤醒、24 小时运行及栈/堆水位。
源码快照见 source，完整性清单见 MANIFEST.json；ZIP 不包含密钥或设备参数。
''', encoding='utf-8')
files = {p.relative_to(OUT).as_posix(): dict(size=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest())
         for p in OUT.rglob('*') if p.is_file()}
manifest = dict(schema_version=1, identity=identity, purpose='HIL only', release_approved=False,
                release_gate='FAILED_INCOMPLETE_STACK_EVIDENCE', host_test_scripts_passed=34,
                git_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                git_dirty=True, files=files)
(OUT / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
for name, info in files.items():
    data = (OUT / name).read_bytes()
    assert len(data) == info['size'] and hashlib.sha256(data).hexdigest() == info['sha256']
archive = OUT.parent / (OUT.name + '.zip')
assert not archive.exists()
with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
    for p in OUT.rglob('*'):
        if p.is_file():
            z.write(p, OUT.name + '/' + p.relative_to(OUT).as_posix())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for name, info in files.items():
        assert hashlib.sha256(z.read(OUT.name + '/' + name)).hexdigest() == info['sha256']
assert all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in hashes.items())
receipt = dict(directory=str(OUT), archive=str(archive), files_verified=len(files),
               zip_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
               hex_roundtrip=True, vectors_and_factory_marker=True, inputs_unchanged=True)
(BUILD / 'delivery-verification.json').write_text(json.dumps(receipt, indent=2))
archive.with_suffix('.zip.sha256').write_text(receipt['zip_sha256'] + '  ' + archive.name + '\n')
print(json.dumps(receipt, indent=2))
