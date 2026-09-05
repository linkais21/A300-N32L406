#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re, shutil, struct, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

ROOT=Path(__file__).resolve().parents[1]
TOOLCHAIN=Path(r"D:\ST\STM32CubeIDE_2.1.1\STM32CubeIDE\plugins\com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32.14.3.rel1.win32_1.0.100.202602081740\tools\bin")
MAKE=Path(r"D:\ST\STM32CubeIDE_2.1.1\STM32CubeIDE\plugins\com.st.stm32cube.ide.mcu.externaltools.make.win32_2.2.100.202601091506\tools\bin\make.exe")
LABEL="N32L406CBL7-DEV-KEY"
MANIFEST=struct.Struct("<6I32s64sI")
CANONICAL=struct.Struct(">6I32s")

def run(command:list[str],cwd:Path=ROOT)->str:
    result=subprocess.run(command,cwd=cwd,capture_output=True,text=True)
    output=result.stdout+result.stderr
    if result.returncode!=0: raise RuntimeError(output)
    if re.search(r"(^|\n).*warning:",output,re.IGNORECASE): raise RuntimeError("build warning rejected:\n"+output)
    return output

def digest(path:Path)->dict:
    blob=path.read_bytes()
    return {"path":path.name,"size":len(blob),"sha256":hashlib.sha256(blob).hexdigest()}

def embedded_public()->bytes:
    text=(ROOT/"include"/"trusted_public_key.h").read_text(encoding="ascii")
    values=re.findall(r"0x([0-9a-fA-F]{2})",text)
    if len(values)!=64: raise RuntimeError("trusted public key header must contain exactly 64 bytes")
    return bytes(int(value,16) for value in values)

def refresh_build_version()->None:
    path=ROOT/"include"/"build_version.h"
    previous=path.read_text(encoding="utf-8")
    match=re.search(r'^#define FW_FULL_VERSION\s+"([^"]+)"',previous,re.MULTILINE)
    if match is None: raise RuntimeError("FW_FULL_VERSION missing from build_version.h")
    now=datetime.now(ZoneInfo("Asia/Shanghai"))
    content=("#ifndef BUILD_VERSION_H\n#define BUILD_VERSION_H\n\n"
             f'#define FW_BUILD_NUMBER  "{now:%Y%m%d_%H%M%S}"\n'
             f'#define FW_BUILD_DATE    "{now:%b %d %Y - %H:%M:%S}"\n'
             f'#define FW_FULL_VERSION  "{match.group(1)}"\n\n#endif /* BUILD_VERSION_H */\n')
    path.write_text(content,encoding="ascii")

def verify_package(path:Path,public:ec.EllipticCurvePublicKey)->None:
    blob=path.read_bytes()
    fields=MANIFEST.unpack_from(blob)
    magic,product,hardware,target,length,version,payload_hash,signature,crc=fields
    payload=blob[MANIFEST.size:]
    if (magic,product,hardware,target)!=(0x4133464D,0x41333030,0x00343036,0x08006000): raise RuntimeError("signed package identity mismatch")
    if length!=len(payload) or hashlib.sha256(payload).digest()!=payload_hash: raise RuntimeError("signed package payload mismatch")
    import zlib
    if zlib.crc32(blob[:120])&0xFFFFFFFF!=crc: raise RuntimeError("signed package CRC mismatch")
    canonical=CANONICAL.pack(magic,product,hardware,target,length,version,payload_hash)
    signed_hash=hashlib.sha256(canonical).digest()
    r=int.from_bytes(signature[:32],"big");s=int.from_bytes(signature[32:],"big")
    public.verify(utils.encode_dss_signature(r,s),signed_hash,ec.ECDSA(utils.Prehashed(hashes.SHA256())))

def main()->int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--key",type=Path,required=True)
    parser.add_argument("--output",type=Path,default=ROOT/"dist"/"dev-key")
    parser.add_argument("--version-counter",type=int,default=20260829)
    args=parser.parse_args()
    if not 0<args.version_counter<=0xFFFFFFFF: parser.error("version counter must be 1..0xffffffff")
    key=serialization.load_pem_private_key(args.key.read_bytes(),password=None)
    if not isinstance(key,ec.EllipticCurvePrivateKey) or not isinstance(key.curve,ec.SECP256R1): raise RuntimeError("DEV key must be P-256")
    numbers=key.public_key().public_numbers()
    public_bytes=numbers.x.to_bytes(32,"big")+numbers.y.to_bytes(32,"big")
    if public_bytes!=embedded_public(): raise RuntimeError("private key does not match embedded public key")

    refresh_build_version()
    run([str(MAKE),"-B","all"])
    run([str(MAKE),"-C","bootloader","-B","all"])
    run([sys.executable,"tools/map_ram_guard.py","app","build/a300_firmware.map"])
    run([sys.executable,"tools/map_ram_guard.py","bootloader","bootloader/build/bootloader.map"])

    build_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out=args.output.resolve()/build_id
    out.mkdir(parents=True,exist_ok=False)
    objcopy=TOOLCHAIN/"arm-none-eabi-objcopy.exe"
    app_bin=out/f"App-{LABEL}.bin";boot_bin=out/f"Bootloader-{LABEL}.bin"
    run([str(objcopy),"-O","binary","build/a300_firmware.elf",str(app_bin)])
    run([str(objcopy),"-O","binary","bootloader/build/bootloader.elf",str(boot_bin)])
    sources={
      "app_elf":ROOT/"build/a300_firmware.elf","app_hex":ROOT/"build/a300_firmware.hex","app_map":ROOT/"build/a300_firmware.map",
      "bootloader_elf":ROOT/"bootloader/build/bootloader.elf","bootloader_map":ROOT/"bootloader/build/bootloader.map"}
    boot_hex=out/f"Bootloader-{LABEL}.hex"
    run([str(objcopy),"-O","ihex",str(sources["bootloader_elf"]),str(boot_hex)])
    artifacts={"app_bin":app_bin,"bootloader_bin":boot_bin,"bootloader_hex":boot_hex}
    for key_name,source in sources.items():
        suffix=source.suffix
        name=("App" if key_name.startswith("app") else "Bootloader")+f"-{LABEL}"+suffix
        target=out/name;shutil.copy2(source,target);artifacts[key_name]=target
    app=app_bin.read_bytes();boot=boot_bin.read_bytes()
    if not 8<=len(app)<=106496 or len(boot)>24576: raise RuntimeError("firmware size outside frozen memory map")
    msp,reset=struct.unpack_from("<II",app)
    if not (0x20000000<=msp<=0x20006000 and msp%8==0 and 0x08006001<=reset<0x08020000 and reset&1): raise RuntimeError("invalid App vectors")
    package=out/f"App-{LABEL}.pkg"
    run([sys.executable,"tools/sign_firmware.py","--key",str(args.key.resolve()),"--input",str(app_bin),"--output",str(package),"--version-counter",str(args.version_counter)])
    verify_package(package,key.public_key());artifacts["signed_app_package"]=package
    combined=bytearray(b"\xFF"*(0x6000+len(app)));combined[:len(boot)]=boot;combined[0x6000:]=app
    combined_path=out/f"Combined-{LABEL}.bin";combined_path.write_bytes(combined);artifacts["combined_bin"]=combined_path
    revision=run(["git","rev-parse","HEAD"]).strip()
    # Git may emit environment warnings (for example, an unreadable global
    # excludes file). They must not invalidate an otherwise successful build.
    git_status=subprocess.run(["git","status","--porcelain"],cwd=ROOT,
                              capture_output=True,text=True,check=True)
    dirty=bool(git_status.stdout.strip())
    toolchain=run([str(TOOLCHAIN/"arm-none-eabi-gcc.exe"),"--version"]).splitlines()[0]
    report={"schema_version":1,"key_label":"DEV-KEY","mcu":"N32L406CBL7",
      "memory":{"boot":[0x08000000,0x08006000],"app":[0x08006000,0x08020000]},
      "version_counter":args.version_counter,"toolchain":toolchain,"git_revision":revision,"git_dirty":dirty,
      "signature_verified":True,"app_vectors":{"msp":msp,"reset":reset},
      "artifacts":{name:digest(path) for name,path in sorted(artifacts.items())}}
    manifest=out/f"SHA256SUMS-{LABEL}.json"
    manifest.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(manifest)
    return 0
if __name__=="__main__":raise SystemExit(main())
