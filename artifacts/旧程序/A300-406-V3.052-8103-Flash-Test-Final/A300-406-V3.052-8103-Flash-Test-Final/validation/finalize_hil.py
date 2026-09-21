"""Explicitly requested HIL delivery; preserves the failed formal RAM gate."""
from pathlib import Path
import hashlib, importlib.util, json, shutil, struct, subprocess, sys, zipfile, zlib
ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'build/params-size-3052'
EXP=ROOT/'build/params-size-final-3052'
APP=EXP/'combined'
OUT=ROOT/'artifacts/A300-406-V3.052-8103-Flash-Test-Final'
TC=ROOT/'.toolchain/bin'
def run(cmd,log,cwd=ROOT):
    r=subprocess.run([str(x) for x in cmd],cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (WORK/log).write_text(r.stdout+r.stderr,encoding='utf-8')
    if r.returncode: raise RuntimeError(f'{log}: exit {r.returncode}')
    return r.stdout
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    hashes=json.loads((EXP/'input-hashes.json').read_text())
    assert all(sha(ROOT/p)==h for p,h in hashes.items())
    gate=(APP/'release-gate.log').read_text()
    assert 'release-guard: PASS' in gate and 'test_platform_trust_anchor: PASS' in gate
    assert 'RAM guard failed: stack evidence: incomplete' in gate
    for name in ['libc.log','frame-budget.log']:
        assert 'PASS' in (APP/name).read_text()
    assert 'warning:' not in (APP/'build.log').read_text()
    spec=importlib.util.spec_from_file_location('builder',ROOT/'tools/build_dev_release.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    # Build the bootloader with the same finalized version header.
    make=ROOT.parent/'tools/w64devkit/w64devkit/bin/make.exe'
    run([make,'-C','bootloader','-B','all','TOOLCHAIN_ROOT='+str(TC)],'boot-final.log')
    bootdir=ROOT/'bootloader/build'
    run([sys.executable,'tools/map_ram_guard.py','bootloader',bootdir/'bootloader.map'],'boot-ram.log')
    app=(APP/'a300_firmware.bin').read_bytes();boot=(bootdir/'bootloader.bin').read_bytes()
    version=b'T360-A300_406_20260823000000,V3.052'
    assert version in app and len(app)==98256
    assert b'V3.051' not in app
    combined=builder.build_combined(boot,app)
    OUT.mkdir(exist_ok=False);dest=OUT/'V3.052';dest.mkdir()
    for prefix,folder,stem in [('App',APP,'a300_firmware'),('Bootloader',bootdir,'bootloader')]:
        for ext in ['bin','hex','elf','map']:shutil.copy2(folder/(stem+'.'+ext),dest/(prefix+'-N32L406CBL7.'+ext))
    (OUT/'SWD-Combined-V3052.bin').write_bytes(combined)
    run([TC/'arm-none-eabi-objcopy.exe','-I','binary','-O','ihex','--change-addresses','0x08000000',OUT/'SWD-Combined-V3052.bin',OUT/'SWD-Combined-V3052.hex'],'hex-final.log')
    run([TC/'arm-none-eabi-objcopy.exe','-I','ihex','-O','binary',OUT/'SWD-Combined-V3052.hex',WORK/'roundtrip-final.bin'],'roundtrip-final.log')
    assert (WORK/'roundtrip-final.bin').read_bytes()==combined
    ota=OUT/'OTA-A300-406-V3052.bin'
    run([sys.executable,'tools/gen_a300_ota_image.py','--input',dest/'App-N32L406CBL7.bin','--output',ota,'--version-code','3052'],'ota-final.log')
    wire=ota.read_bytes()
    assert struct.unpack('<IIIII12s',wire[:32])==(0xA300B007,3052,len(app),zlib.crc32(app)&0xffffffff,0x41333030,bytes(12))
    assert wire[32:]==app and combined[0x6000:]==app
    validation=OUT/'validation';validation.mkdir()
    for folder in [WORK,APP]:
        for p in folder.iterdir():
            if p.is_file() and p.suffix in ['.log','.json','.py']:shutil.copy2(p,validation/p.name)
    # Include original inputs AND the actual generated source replacements.
    provenance=dest/'provenance'
    for name in hashes:
        p=provenance/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,p)
    shutil.copytree(APP/'sources',dest/'compiled-overlays')
    shutil.copy2(ROOT/'docs/params-v3052-hil.md',OUT/'README.md')
    manifest=dict(version='V3.052',version_counter=3052,release_approved=False,
        formal_gate='failed: incomplete whole-program stack/heap/IRQ evidence',
        app_bytes=len(app),remaining_bytes=106496-len(app),combined_bytes=len(combined),
        build_command='python tools/experiments/firmware_size_trial.py --math bounded --quantize-mm --cases combined --output <new-build-directory>',
        artifacts={p.relative_to(OUT).as_posix():dict(bytes=p.stat().st_size,sha256=sha(p)) for p in OUT.rglob('*') if p.is_file() and p.suffix in ['.bin','.hex','.elf','.map']})
    (OUT/'MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (OUT/'SHA256SUMS.txt').write_text('\n'.join(sha(p)+'  '+p.relative_to(OUT).as_posix() for p in sorted(OUT.rglob('*')) if p.is_file())+'\n',encoding='utf-8')
    archive=Path(str(OUT)+'.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(OUT.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(OUT.parent))
    with zipfile.ZipFile(archive) as z:assert z.testzip() is None
    Path(str(archive)+'.sha256').write_text(sha(archive)+'  '+archive.name+'\n')
    assert all(sha(ROOT/p)==h for p,h in hashes.items())
    print(archive);print('App',len(app),'remaining',106496-len(app),'ZIP SHA256',sha(archive))
if __name__=='__main__':main()
