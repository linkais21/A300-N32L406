from pathlib import Path
import hashlib, json, shutil, subprocess, sys

ROOT = Path(__file__).resolve().parents[1]
WORK = Path(__file__).resolve().parent
LOG = WORK / 'validation'
LOG.mkdir(exist_ok=True)
MAKE = ROOT.parent / 'tools/w64devkit/w64devkit/bin/mingw32-make.exe'
TC = ROOT / '.toolchain/bin'
results = []

def run(name, args, cwd=ROOT, allowed=(0,)):
    p = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True)
    (LOG / (name + '.log')).write_bytes(p.stdout + p.stderr)
    results.append(dict(name=name, exit_code=p.returncode, command=[str(a) for a in args]))
    (LOG / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(name, p.returncode, flush=True)
    if p.returncode not in allowed:
        raise RuntimeError(name + ': see validation log')

manifest = json.loads((ROOT/'build-production-20260917/DELIVERY_INPUTS.json').read_text(encoding='utf-8'))
for group in ('inputs', 'outputs'):
    for name, expected in manifest[group].items():
        assert hashlib.sha256((ROOT.parent/name).read_bytes()).hexdigest() == expected, name

# Build Bootloader in a source snapshot: never overwrite existing build outputs.
snapshot = WORK/'source'
snapshot.mkdir(exist_ok=False)
for folder in ('include','src','third_party','sdk','ldscript'):
    shutil.copytree(ROOT/folder, snapshot/folder)
for folder in ('src','include','ldscript'):
    shutil.copytree(ROOT/'bootloader'/folder, snapshot/'bootloader'/folder)
shutil.copy2(ROOT/'bootloader/Makefile', snapshot/'bootloader/Makefile')
for name in ('Makefile','release_identity.json'):
    shutil.copy2(ROOT/name, snapshot/name)
hashes = {p.relative_to(snapshot).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
          for p in snapshot.rglob('*') if p.is_file()}
(LOG/'source-hashes.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
run('app-build',[MAKE,'-s','all','BUILD=build-production-20260917'])
run('boot-build',[MAKE,'-s','-B','all','TOOLCHAIN_ROOT='+TC.as_posix()], snapshot/'bootloader')
run('boot-ram',[sys.executable,'tools/map_ram_guard.py','bootloader',snapshot/'bootloader/build/bootloader.map'])
run('release-guard',[MAKE,'-s','release-guard','BUILD=build-production-20260917'])
run('release-gate',[MAKE,'-s','release-gate','BUILD=build-production-20260917'],allowed=(0,2))
gate=(LOG/'release-gate.log').read_text(encoding='utf-8',errors='replace')
assert results[-1]['exit_code']==0 or 'incomplete stack evidence' in gate, gate[-2000:]
for test in ('test_platform_trust_anchor','test_release_identity_contract','test_dev_release_manifest',
             'test_bootloader_factory_init','test_factory_init_artifact','test_bootloader_platform_contract',
             'test_bootloader_bcr_failclosed','test_boot_cold_start_recovery','test_boot_spi_timing',
             'test_flash_combined_script','test_production_test'):
    args=[sys.executable,'tools/tests/'+test+'.py']
    if test=='test_production_test': args += ['--wire-output',str(WORK/'production-wire.txt')]
    run(test,args)
run('tester-protocol',['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',
    ROOT.parent/'生产测试工具/A300ProductionTester/tools/test_protocol.ps1','-FirmwareReplies',WORK/'production-wire.txt'])
print('Preparation complete; release status retained in logs.',flush=True)
