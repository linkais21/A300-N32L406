"""One-off user-requested HIL pair. Failed release status is preserved, not waived."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import importlib.util
import json
import re
import shutil
import struct
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/HIL-OPT-20260913-V3038-V3039'
WORK = ROOT / 'build/hil-opt-20260913'
MAKE = ROOT.parent / 'tools/w64devkit/w64devkit/bin/make.exe'
TC = ROOT / '.toolchain/bin'
COMMANDS = []

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def run(command, log, cwd=ROOT, expected_ram_failure=False):
    result = subprocess.run([str(x) for x in command], cwd=cwd, capture_output=True,
                            text=True, encoding='utf-8', errors='replace')
    output = result.stdout + result.stderr
    (WORK / log).write_text(output, encoding='utf-8')
    COMMANDS.append({'command': [str(x) for x in command], 'cwd': str(cwd),
                     'exit_code': result.returncode, 'log': log})
    (WORK / 'commands.json').write_text(json.dumps(COMMANDS, indent=2), encoding='utf-8')
    if expected_ram_failure:
        assert result.returncode != 0, 'Expected documented failed release status; review if changed'
        assert 'release-guard: PASS' in output
        assert 'known call-frame estimate already breaches required runtime gap' in output, output
        assert 'stack-guard: INCOMPLETE' in output
    else:
        assert result.returncode == 0, output
        assert not re.search(r'(^|\n).*warning:', output, re.I), output
    print(log, 'EXPECTED RAM BLOCK' if expected_ram_failure else 'PASS', flush=True)
    return output

def digest(path):
    b=path.read_bytes()
    return {'path':path.name,'size':len(b),'sha256':hashlib.sha256(b).hexdigest()}

def set_version(revision):
    identity=json.loads((ROOT/'release_identity.json').read_text(encoding='utf-8'))
    old=identity['firmware_version']; old_counter=identity['firmware_version_counter']
    identity.update(firmware_revision=revision, firmware_version=identity['firmware_version_prefix']+f'{revision:03d}',
                    firmware_version_counter=3000+revision)
    (ROOT/'release_identity.json').write_text(json.dumps(identity,indent=2)+'\n',encoding='utf-8')
    p=ROOT/'include/config.h'; text=p.read_text(encoding='utf-8')
    assert text.count(old)==1
    p.write_text(text.replace(old,identity['firmware_version']),encoding='utf-8')
    builder=load('hil_builder',ROOT/'tools/build_dev_release.py')
    builder.refresh_build_version()
    p=ROOT/'tools/tests/test_release_identity_contract.py'; text=p.read_text(encoding='utf-8')
    text=text.replace(old,identity['firmware_version']).replace(f'"firmware_version_counter": {old_counter}',f'"firmware_version_counter": {3000+revision}')
    text=re.sub(r'"firmware_revision": \d+,',f'"firmware_revision": {revision},',text)
    p.write_text(text,encoding='utf-8')
    # Only reviewed version fields changed. Preserve every identity-flow rule.
    guard=load('hil_guard',ROOT/'tools/release_guard.py')
    p=ROOT/'tools/release_guard.py'; text=p.read_text(encoding='utf-8')
    for name in ['include/config.h','include/build_version.h']:
        old_digest=guard.CANONICAL_IDENTITY_FILE_SHA256[name]
        new_digest=guard.canonical_file_digest((ROOT/name).read_text(encoding='utf-8'),name)
        assert text.count(old_digest)==1
        text=text.replace(old_digest,new_digest)
    p.write_text(text,encoding='utf-8')
    return identity

def package(identity, app_dir, boot_dir):
    counter=identity['firmware_version_counter']; dest=OUT/f'V3.{counter-3000:03d}'
    dest.mkdir()
    artifacts={}
    for prefix, source, stem in [('app',app_dir,'a300_firmware'),('bootloader',boot_dir,'bootloader')]:
        for suffix in ['bin','hex','elf','map']:
            target=dest/f'{prefix.capitalize()}-N32L406CBL7.{suffix}'
            shutil.copy2(source/f'{stem}.{suffix}',target);artifacts[f'{prefix}_{suffix}']=target
    app=artifacts['app_bin'].read_bytes();boot=artifacts['bootloader_bin'].read_bytes()
    assert 8<=len(app)<=106496 and 8<=len(boot)<=24576
    msp,reset=struct.unpack_from('<II',app)
    assert 0x20000000<=msp<=0x20006000 and msp%8==0 and reset&1 and 0x08006000<=reset<0x08020000
    bmsp,breset=struct.unpack_from('<II',boot)
    assert 0x20000000<=bmsp<=0x20006000 and bmsp%8==0 and breset&1 and 0x08000000<=breset<0x08006000
    assert identity['firmware_version'].encode() in app
    keytext=(ROOT/'include/trusted_public_key.h').read_text(encoding='utf-8')
    key=bytes(int(x,16) for x in re.findall(r'0x([0-9a-fA-F]{2})(?=\s*[,}])',keytext))
    assert len(key)==64 and app.count(key)==1 and boot.count(key)==1
    ota=dest/f'A300-406-OTA-V{counter}.bin'
    run([sys.executable,ROOT/'tools/gen_a300_ota_image.py','--input',artifacts['app_bin'],'--output',ota,
         '--version-code',counter],f'V{counter}-ota.log')
    wire=ota.read_bytes();header=struct.unpack('<IIIII12s',wire[:32])
    assert header==(0xA300B007,counter,len(app),zlib.crc32(app)&0xffffffff,0x41333030,bytes(12))
    assert wire[32:]==app
    artifacts['ota_upload_bin']=ota
    combined=bytearray(b'\xff'*(0x6000+len(app)));combined[:len(boot)]=boot;combined[0x6000:]=app
    target=dest/'Combined-N32L406CBL7.bin';target.write_bytes(combined);artifacts['combined_bin']=target
    combined_hex=dest/'Combined-N32L406CBL7.hex'
    run([TC/'arm-none-eabi-objcopy.exe','-I','binary','-O','ihex','--change-addresses','0x08000000',target,combined_hex],f'V{counter}-combined-hex.log')
    artifacts['combined_hex']=combined_hex
    for name in ['flash-capacity.json','stack-analysis.json','stack-evidence.json']:
        target=dest/name;shutil.copy2(app_dir/name,target);artifacts[name]=target
    cap=json.loads((app_dir/'flash-capacity.json').read_text())
    assert cap['used_bytes']==len(app) and cap['status']=='passed'
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    report={'schema_version':1,'purpose':'user-requested hardware validation only','release_approved':False,
            'release_gate':'failed: RAM gap and incomplete stack evidence','signing':'platform-detached',
            'ota_format':'a300-header-v1','mcu':'N32L406CBL7',
            'memory':{'boot':[0x08000000,0x08006000],'app':[0x08006000,0x08020000]},
            'version_counter':counter,'firmware_version':identity['firmware_version'],
            'toolchain':subprocess.check_output([str(TC/'arm-none-eabi-gcc.exe'),'--version'],text=True).splitlines()[0],
            'git_revision':revision,'git_dirty':True,'app_vectors':{'msp':msp,'reset':reset},
            'artifacts':{name:digest(path) for name,path in artifacts.items()}}
    manifest=dest/'SHA256SUMS-N32L406CBL7.json'
    manifest.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    run([sys.executable,ROOT/'tools/tests/test_dev_release_manifest.py','--manifest',manifest],f'V{counter}-manifest.log')
    provenance=dest/'provenance';provenance.mkdir()
    for name in ['release_identity.json','include/config.h','include/build_version.h','tools/release_guard.py','tools/tests/test_release_identity_contract.py']:
        target=provenance/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
    inputs={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ['src','include','ldscript','bootloader/src','bootloader/include']
            for p in (ROOT/folder).rglob('*') if p.is_file()}
    (provenance/'source-hashes.json').write_text(json.dumps(inputs,indent=2),encoding='utf-8')
    return dest

def main():
    OUT.mkdir(parents=True,exist_ok=False);WORK.mkdir(parents=True,exist_ok=False)
    run([sys.executable,'tools/tests/test_platform_trust_anchor.py'],'platform-trust.log')
    boot_rel='../build/hil-opt-20260913/boot'
    mk=(ROOT/'bootloader/Makefile').read_text(encoding='utf-8')
    mk=re.sub(r'\bbuild\b',boot_rel,mk)
    boot_mk=WORK/'boot-hil.mk';boot_mk.write_text(mk,encoding='utf-8')
    run([MAKE,'-f',boot_mk,'-B','-j4','all',f'TOOLCHAIN_ROOT={TC.as_posix()}'],'boot-build.log',ROOT/'bootloader')
    boot_dir=WORK/'boot'
    run([sys.executable,'tools/map_ram_guard.py','bootloader',boot_dir/'bootloader.map'],'boot-guard.log')
    for rev in [38,39]:
        ident=set_version(rev);counter=3000+rev
        run([sys.executable,'tools/tests/test_release_identity_contract.py'],f'V{counter}-identity.log')
        build=f'build/hil-opt-20260913/V{counter}'
        run([MAKE,'-B','-j4','all',f'BUILD={build}',f'TOOLCHAIN_DIR={TC.as_posix()}'],f'V{counter}-build.log')
        run([MAKE,'release-gate',f'BUILD={build}',f'TOOLCHAIN_DIR={TC.as_posix()}'],f'V{counter}-release-gate.log',expected_ram_failure=True)
        run([sys.executable,'tools/libc_parser_guard.py',f'{build}/a300_firmware.map'],f'V{counter}-libc.log')
        package(ident,ROOT/build,boot_dir)
    shutil.copy2(OUT/'V3.038/Combined-N32L406CBL7.bin',OUT/'SWD-Combined-V3038.bin')
    shutil.copy2(OUT/'V3.038/Combined-N32L406CBL7.hex',OUT/'SWD-Combined-V3038.hex')
    shutil.copy2(OUT/'V3.039/A300-406-OTA-V3039.bin',OUT/'OTA-A300-406-V3039.bin')
    print(OUT,flush=True)

if __name__=='__main__':main()
