"""Package the explicitly requested HIL image; retain the failed release status."""
from pathlib import Path
import hashlib
import importlib.util
import json
import re
import shutil
import struct
import subprocess
import sys
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'build/flash-audit-3051'
OUT = ROOT / 'artifacts/A300-406-V3.051-Flash-Test'
TC = ROOT / '.toolchain/bin'

def run(args):
    return subprocess.check_output([str(a) for a in args], cwd=ROOT, text=True)

def digest(path):
    data = path.read_bytes()
    return dict(path=path.name, size=len(data), sha256=hashlib.sha256(data).hexdigest())

def main():
    hashes = json.loads((WORK/'source-hashes.json').read_text())
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == h for p,h in hashes.items())
    identity = json.loads((ROOT/'release_identity.json').read_text())
    assert identity['firmware_version_counter'] == 3051
    gate = (WORK/'release-gate.log').read_text(encoding='utf-8-sig')
    assert 'release-guard: PASS' in gate and 'RAM guard failed: stack evidence: incomplete stack evidence' in gate
    assert 'test_platform_trust_anchor: PASS' in gate
    for name in ['app-build.log', 'boot-build.log']:
        assert not re.search(r'warning:|error:', (WORK/name).read_text(encoding='utf-8-sig'), re.I)
    tests = json.loads((WORK/'tests-final.json').read_text())
    assert all(r['exit_code'] == 0 for r in tests)
    spec = importlib.util.spec_from_file_location('builder', ROOT/'tools/build_dev_release.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    app = (WORK/'app/a300_firmware.bin').read_bytes()
    boot = (WORK/'boot/bootloader.bin').read_bytes()
    assert len(app) <= 106496 and len(boot) <= 24576
    assert identity['firmware_version'].encode() in app
    bmsp, breset = struct.unpack_from('<II', boot)
    assert 0x20000000 <= bmsp <= 0x20006000 and bmsp % 8 == 0
    assert breset & 1 and 0x08000000 <= breset < 0x08005800
    combined = builder.build_combined(boot, app)
    msp, reset = builder.validate_app_vectors(app)
    cap = json.loads((WORK/'app/flash-capacity.json').read_text())
    assert cap['status'] == 'passed' and cap['used_bytes'] == len(app)
    OUT.mkdir(exist_ok=False)
    dest = OUT/'V3.051'
    dest.mkdir()
    artifacts = {}
    for prefix, folder, stem in [('app','app','a300_firmware'),('bootloader','boot','bootloader')]:
        for ext in ['bin','hex','elf','map']:
            target = dest/f'{prefix.capitalize()}-N32L406CBL7.{ext}'
            shutil.copy2(WORK/folder/f'{stem}.{ext}', target)
            artifacts[prefix+'_'+ext] = target
    target = dest/'Combined-N32L406CBL7.bin'
    target.write_bytes(combined)
    artifacts['combined_bin'] = target
    target_hex = dest/'Combined-N32L406CBL7.hex'
    run([TC/'arm-none-eabi-objcopy.exe','-I','binary','-O','ihex','--change-addresses','0x08000000',target,target_hex])
    artifacts['combined_hex'] = target_hex
    roundtrip = WORK/'combined-roundtrip.bin'
    run([TC/'arm-none-eabi-objcopy.exe','-I','ihex','-O','binary',target_hex,roundtrip])
    assert roundtrip.read_bytes() == combined
    ota = dest/'A300-406-OTA-V3051.bin'
    run([sys.executable,'tools/gen_a300_ota_image.py','--input',artifacts['app_bin'],'--output',ota,'--version-code','3051'])
    wire = ota.read_bytes()
    assert struct.unpack('<IIIII12s',wire[:32]) == (0xA300B007,3051,len(app),zlib.crc32(app)&0xffffffff,0x41333030,bytes(12))
    assert wire[32:] == app and combined[0x6000:] == app
    artifacts['ota_upload_bin'] = ota
    for name in ['flash-capacity.json','flash-build-profile.json','stack-evidence.json','stack-analysis.json']:
        target = dest/name
        shutil.copy2(WORK/'app'/name,target)
        artifacts[name] = target
    manifest = dict(schema_version=1, purpose='user-requested hardware validation only',
                    release_approved=False, release_gate='failed: incomplete whole-program stack/heap/exception evidence',
                    signing='platform-detached', ota_format='a300-header-v1', mcu='N32L406CBL7',
                    memory={'boot':[0x08000000,0x08006000],'app':[0x08006000,0x08020000]},
                    version_counter=3051, firmware_version=identity['firmware_version'],
                    toolchain=run([TC/'arm-none-eabi-gcc.exe','--version']).splitlines()[0],
                    git_revision=run(['git','rev-parse','HEAD']).strip(), git_dirty=True,
                    app_vectors={'msp':msp,'reset':reset},
                    artifacts={k:digest(v) for k,v in artifacts.items()})
    manifest_path = dest/'SHA256SUMS-N32L406CBL7.json'
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(run([sys.executable,'tools/tests/test_dev_release_manifest.py','--manifest',manifest_path]))
    for source,name in [(artifacts['combined_bin'],'SWD-Combined-V3051.bin'),
                        (artifacts['combined_hex'],'SWD-Combined-V3051.hex'),(ota,'OTA-A300-406-V3051.bin')]:
        shutil.copy2(source,OUT/name)
    for name in ['README.md','PONYTAIL-AUDIT.md','FLASH-ASSESSMENT.md']:
        shutil.copy2(WORK/name,OUT/name)
    validation = OUT/'validation'
    validation.mkdir()
    for p in WORK.iterdir():
        if p.is_file() and p.suffix in ['.log','.json','.mk','.py']:
            shutil.copy2(p,validation/p.name)
    provenance = dest/'provenance'
    for name in hashes:
        target = provenance/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/name,target)
    lines = [f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(OUT).as_posix()}'
             for p in sorted(OUT.rglob('*')) if p.is_file()]
    (OUT/'SHA256SUMS.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    archive = Path(str(OUT)+'.zip')
    assert not archive.exists()
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(OUT.rglob('*')):
            if p.is_file(): z.write(p,p.relative_to(OUT.parent))
    with zipfile.ZipFile(archive) as z: assert z.testzip() is None
    Path(str(archive)+'.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == h for p,h in hashes.items())
    print(archive)
    print(json.dumps({'app':len(app),'boot_bin_span':len(boot),'combined':len(combined),'remaining':106496-len(app)}))

if __name__ == '__main__': main()
