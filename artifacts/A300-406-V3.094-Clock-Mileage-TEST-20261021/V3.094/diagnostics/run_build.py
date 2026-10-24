from pathlib import Path
import json,re,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];WORK=Path(__file__).resolve().parent
APP=WORK/'app';BOOT=WORK/'boot'
BASE=ROOT/'artifacts/A300-406-V3.094-Clock-Mileage-TEST-20261021'
TOOLCHAIN=ROOT.parents[2]/'A300_Tools/toolchains/arm-gnu-toolchain-14.3.rel1/bin'
MAKE=ROOT.parent/'tools/w64devkit/w64devkit/bin/mingw32-make.exe'
sys.path.insert(0,str(ROOT))
from tools.build_dev_release import build_combined,validate_app_vectors,validate_factory_init_marker,digest
commands=[]
def run(command,log,cwd=ROOT):
    record={'cwd':str(cwd),'command':[str(x) for x in command],'log':log}
    print('Running '+log,flush=True)
    result=subprocess.run(record['command'],cwd=cwd,capture_output=True,timeout=600)
    data=result.stdout+result.stderr;(WORK/log).write_bytes(data)
    record['exit_code']=result.returncode;commands.append(record)
    (WORK/'build-commands.json').write_text(json.dumps(commands,indent=2)+'\n',encoding='utf-8')
    if result.returncode or re.search(rb'\bwarning:',data,re.I):
        print(data.decode('utf-8',errors='replace')[-7000:],flush=True)
        raise RuntimeError(f'{log} failed or contains compiler warnings: {result.returncode}')
    print(log+': PASS',flush=True)
    return data
assert TOOLCHAIN.joinpath('arm-none-eabi-gcc.exe').is_file() and MAKE.is_file()
assert not BASE.exists()
run([sys.executable,'tools/tests/test_platform_trust_anchor.py'],'platform-trust.log')
app_arg='BUILD='+APP.relative_to(ROOT).as_posix();tool_arg='TOOLCHAIN_DIR='+TOOLCHAIN.as_posix()
run([MAKE,'all',app_arg,tool_arg],'app-build.log')
run([MAKE,'release-gate',app_arg,tool_arg],'release-gate.log')
# Production boot make hardcodes build/. Relocate output paths in an ignored
# copy, keeping sources, compiler flags and linker layout identical.
boot_make=(ROOT/'bootloader/Makefile').read_text(encoding='utf-8')
boot_make=re.sub(r'(?<![A-Za-z0-9_])build(?![A-Za-z0-9_])', '../'+BOOT.relative_to(ROOT).as_posix(), boot_make)
generated=WORK/'boot-release.mk';generated.write_text(boot_make,encoding='utf-8')
run([MAKE,'-f','../'+generated.relative_to(ROOT).as_posix(),'all','SHELL=cmd.exe',
     'TOOLCHAIN_ROOT='+TOOLCHAIN.as_posix()],'boot-build.log',ROOT/'bootloader')
run([sys.executable,'tools/map_ram_guard.py','bootloader',BOOT/'bootloader.map'],'boot-ram.log')
identity=json.loads((ROOT/'release_identity.json').read_text(encoding='utf-8'))
assert identity['firmware_revision']==94 and identity['firmware_version_counter']==3094
out=BASE/'V3.094';out.mkdir(parents=True,exist_ok=False);artifacts={}
for prefix,build_dir,stem in [('app',APP,'App'),('bootloader',BOOT,'Bootloader')]:
    source_stem='a300_firmware' if prefix=='app' else 'bootloader'
    for suffix in ['bin','hex','elf','map']:
        p=out/(stem+'-N32L406CBL7.'+suffix)
        shutil.copy2(build_dir/(source_stem+'.'+suffix),p);artifacts[prefix+'_'+suffix]=digest(p)
app=(out/'App-N32L406CBL7.bin').read_bytes();boot=(out/'Bootloader-N32L406CBL7.bin').read_bytes()
validate_app_vectors(app);validate_factory_init_marker(boot)
combined=out/'Combined-N32L406CBL7.bin';combined.write_bytes(build_combined(boot,app));artifacts['combined_bin']=digest(combined)
ota=out/'A300-406-OTA-V3094.bin'
run([sys.executable,'tools/gen_a300_ota_image.py','--input',out/'App-N32L406CBL7.bin',
     '--output',ota,'--version-code','3094'],'ota-generation.log')
artifacts['ota_upload_bin']=digest(ota)
shutil.copy2(APP/'flash-capacity.json',out/'flash-capacity.json');artifacts['flash_capacity']=digest(out/'flash-capacity.json')
report={'schema_version':1,'signing':'platform-detached','ota_format':'a300-header-v1','mcu':'N32L406CBL7',
        'memory':{'boot':[0x08000000,0x08006000],'app':[0x08006000,0x08020000]},'version_counter':3094,
        'toolchain':subprocess.check_output([str(TOOLCHAIN/'arm-none-eabi-gcc.exe'),'--version']).decode().splitlines()[0],
        'git_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip(),'git_dirty':True,
        'app_vectors':dict(zip(['msp','reset'],validate_app_vectors(app))),'artifacts':artifacts}
(out/'SHA256SUMS-N32L406CBL7.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(identity['firmware_version'],flush=True)
print(f'App={len(app)}; Flash free={106496-len(app)}; package={out}',flush=True)
