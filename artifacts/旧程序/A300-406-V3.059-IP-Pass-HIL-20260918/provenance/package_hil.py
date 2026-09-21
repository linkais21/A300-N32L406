"""Package already-built V3.059 HIL images; never builds or flashes hardware."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_dev_release import build_combined

BUILD = ROOT / 'build-pass-v3059-hil-20260918'
EVIDENCE = ROOT / 'build-pass-evidence-20260918'
DEST = ROOT / 'artifacts/A300-406-V3.059-IP-Pass-HIL-20260918'
ZIP = Path(str(DEST) + '.zip')
assert not DEST.exists() and not ZIP.exists(), 'Refusing to overwrite a delivery'
results = json.loads((EVIDENCE / 'test-results.json').read_text(encoding='utf-8'))
assert len(results) == 48 and all(r['exit_code'] == 0 for r in results)
identity = json.loads((ROOT / 'release_identity.json').read_text(encoding='utf-8'))
assert identity['firmware_version_counter'] == 3059
DEST.mkdir(parents=True)

def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)

for source_dir, old, new in [
    (BUILD, 'a300_firmware', 'App-N32L406CBL7'),
    (BUILD / 'boot-stage/bootloader/build', 'bootloader', 'Bootloader-N32L406CBL7'),
]:
    for ext in ('bin', 'hex', 'elf', 'map'):
        copy(source_dir / f'{old}.{ext}', DEST / f'{new}.{ext}')
app = (DEST / 'App-N32L406CBL7.bin').read_bytes()
boot = (DEST / 'Bootloader-N32L406CBL7.bin').read_bytes()
combined = build_combined(boot, app)
assert len(app) == 106476 and len(combined) == 131052
assert combined[:len(boot)] == boot and combined[0x6000:] == app
assert combined[len(boot):0x6000] == b'\xff' * (0x6000-len(boot))
(DEST / 'Combined-N32L406CBL7.bin').write_bytes(combined)
subprocess.run([
    'D:/A300_Tools/toolchains/arm-gnu-toolchain-14.3.rel1/bin/arm-none-eabi-objcopy.exe',
    '-I', 'binary', '-O', 'ihex', '--change-addresses', '0x08000000',
    str(DEST / 'Combined-N32L406CBL7.bin'), str(DEST / 'Combined-N32L406CBL7.hex'),
], check=True)

def check_hex(path, expected, base):
    memory = {}
    upper = 0
    eof = False
    for line in path.read_text(encoding='ascii').splitlines():
        assert line.startswith(':') and not eof
        record = bytes.fromhex(line[1:])
        assert len(record) == record[0]+5 and sum(record) % 256 == 0
        count, kind = record[0], record[3]
        offset = int.from_bytes(record[1:3], 'big')
        data = record[4:4+count]
        if kind == 0:
            for i, value in enumerate(data):
                address = upper+offset+i
                assert address not in memory
                memory[address] = value
        elif kind == 4:
            upper = int.from_bytes(data, 'big') << 16
        elif kind == 2:
            upper = int.from_bytes(data, 'big') << 4
        elif kind == 1:
            eof = True
        else:
            assert kind in (3, 5)
    assert eof and min(memory) == base and max(memory) == base+len(expected)-1
    # Linked HEX may omit padding; BIN represents those gaps as zero.
    assert bytes(memory.get(base+i, 0) for i in range(len(expected))) == expected

check_hex(DEST / 'Combined-N32L406CBL7.hex', combined, 0x08000000)
check_hex(DEST / 'App-N32L406CBL7.hex', app, 0x08006000)
check_hex(DEST / 'Bootloader-N32L406CBL7.hex', boot, 0x08000000)
for name in ('flash-capacity.json', 'flash-build-profile.json', 'stack-analysis.json', 'stack-evidence.json'):
    copy(BUILD / name, DEST / name)
copy(ROOT / 'release_identity.json', DEST / 'release_identity.json')
copy(ROOT / 'docs/pass-v3059-hil-20260918.md', DEST / 'README.md')
for name in ['test-results.json', 'build-v3059.log', 'boot-v3059.log', 'release-gate-v3059.log'] + [r['log'] for r in results]:
    copy(EVIDENCE / name, DEST / 'validation' / name)
# Capture project-owned source and test inputs, excluding runtime data and credentials.
for directory in ('src', 'include', 'ldscript', 'bootloader/src', 'bootloader/include', 'bootloader/ldscript', 'tools'):
    for source in (ROOT / directory).rglob('*'):
        if source.is_file() and source.suffix in ('.c', '.h', '.S', '.s', '.ld', '.py', '.ps1', '.json') and '__pycache__' not in source.parts:
            copy(source, DEST / 'provenance' / source.relative_to(ROOT))
for name in ('Makefile', 'bootloader/Makefile', 'release_identity.json'):
    copy(ROOT / name, DEST / 'provenance' / name)
copy(Path(__file__), DEST / 'provenance/package_hil.py')
manifest = {
    'purpose': 'HIL', 'release_approved': False, 'identity': identity,
    'toolchain': 'ARM GNU 14.3.Rel1 (GCC 14.3.1)',
    'app_build': 'make -s -j4 size flash-guard BUILD=build-pass-v3059-hil-20260918 "SIZE_FLAGS=-Os -finline-limit=128"',
    'combined_base': '0x08000000', 'app_base': '0x08006000',
    'combined_bytes': len(combined), 'app_bytes': len(app), 'flash_free_bytes': 20,
    'host_test_scripts_passed': 48, 'release_identity_guard': 'PASS',
    'ram_gate': 'FAIL: incomplete whole-program stack/heap/exception bound',
    'hardware_tested': False, 'stationary_drift_algorithm_changed': False,
    'factory_initialization': 'First boot clears config, BCR, OTA checkpoints and authorization records; save settings before flashing.',
    'source_snapshot': 'Current project-owned sources and tools; vendor SDK/toolchain dependencies remain external.',
}
(DEST / 'MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
hashes = {p.relative_to(DEST).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(DEST.rglob('*')) if p.is_file()}
(DEST / 'SHA256SUMS.txt').write_text(''.join(f'{value}  {name}\n' for name, value in hashes.items()), encoding='utf-8')
with zipfile.ZipFile(ZIP, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(DEST.rglob('*')):
        if path.is_file():
            archive.write(path, DEST.name+'/'+path.relative_to(DEST).as_posix())
with zipfile.ZipFile(ZIP) as archive:
    assert archive.testzip() is None
    for name, digest in hashes.items():
        assert hashlib.sha256(archive.read(DEST.name+'/'+name)).hexdigest() == digest
zip_hash = hashlib.sha256(ZIP.read_bytes()).hexdigest()
ZIP.with_suffix('.zip.sha256').write_text(f'{zip_hash}  {ZIP.name}\n', encoding='ascii')
print(json.dumps({'package': str(ZIP), 'sha256': zip_hash, 'combined_bytes': len(combined), 'files_verified': len(hashes), 'hex_and_zip_verification': 'PASS'}, indent=2))
