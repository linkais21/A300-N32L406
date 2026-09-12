#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, struct, subprocess, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
TOOLCHAIN=Path(os.environ.get("A300_TOOLCHAIN_DIR", ROOT / ".toolchain" / "bin"))
MAKE=Path(os.environ.get(
    "A300_MAKE",
    shutil.which("make") or ROOT.parent / "tools" / "w64devkit" / "w64devkit" / "bin" / "make.exe",
))
LABEL="N32L406CBL7"
VERSION_LABEL_RE = re.compile(r"(?:^|,)V[0-9]+\.[0-9]{3}$")

def run(command:list[str],cwd:Path=ROOT)->str:
    result=subprocess.run(command,cwd=cwd,capture_output=True,text=True)
    output=result.stdout+result.stderr
    if result.returncode!=0: raise RuntimeError(output)
    if re.search(r"(^|\n).*warning:",output,re.IGNORECASE): raise RuntimeError("build warning rejected:\n"+output)
    return output

def digest(path:Path)->dict:
    blob=path.read_bytes()
    return {"path":path.name,"size":len(blob),"sha256":hashlib.sha256(blob).hexdigest()}

def release_identity() -> dict:
    identity=json.loads((ROOT/"release_identity.json").read_text(encoding="utf-8"))
    counter=identity.get("firmware_version_counter")
    if type(counter) is not int or not 0<counter<=0xFFFFFFFF:
        raise ValueError("release_identity.json firmware_version_counter must be 1..0xffffffff")
    return identity

def release_version_label(identity: dict) -> str:
    version = identity.get("firmware_version")
    if not isinstance(version, str):
        raise ValueError("release_identity.json firmware_version must end in V<major>.<revision>")
    match = VERSION_LABEL_RE.search(version)
    if match is None:
        raise ValueError("release_identity.json firmware_version must end in V<major>.<revision>")
    return match.group(0).lstrip(",")

def release_output_dir(output_root: Path, identity: dict) -> Path:
    return output_root / release_version_label(identity)

def reserve_release_dir(output_root: Path, identity: dict) -> Path:
    path = release_output_dir(output_root.resolve(), identity)
    path.mkdir(parents=True, exist_ok=False)
    return path

def refresh_build_version()->None:
    path=ROOT/"include"/"build_version.h"
    identity=release_identity()
    version=identity["firmware_version"]
    counter=identity["firmware_version_counter"]
    now=datetime.now(ZoneInfo("Asia/Shanghai"))
    content=("/* Auto-generated build version - DO NOT EDIT */\n"
             "#ifndef BUILD_VERSION_H\n#define BUILD_VERSION_H\n\n"
             f'#define FW_BUILD_NUMBER  "{now:%Y%m%d_%H%M%S}"\n'
             f'#define FW_BUILD_DATE    "{now:%b %d %Y - %H:%M:%S}"\n'
             f'#define FW_FULL_VERSION  "{version}"\n'
             f'#define FW_VERSION_COUNTER  {counter}UL\n\n#endif /* BUILD_VERSION_H */\n')
    path.write_text(content,encoding="ascii")

def main()->int:
    identity=release_identity()
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=ROOT/"artifacts")
    parser.add_argument("--version-counter",type=int,default=identity["firmware_version_counter"])
    args=parser.parse_args()
    if not 0<args.version_counter<=0xFFFFFFFF: parser.error("version counter must be 1..0xffffffff")
    if args.version_counter != identity["firmware_version_counter"]:
        parser.error("--version-counter must match release_identity.json firmware_version_counter")
    if not MAKE.is_file(): raise RuntimeError(f"make executable not found: {MAKE}")
    objcopy=TOOLCHAIN/"arm-none-eabi-objcopy.exe"
    if not objcopy.is_file(): raise RuntimeError(f"ARM objcopy not found: {objcopy}")

    # Verify the actual embedded key against a platform signature before any
    # release directory or firmware is generated (not a generated test key).
    run([sys.executable,"tools/tests/test_platform_trust_anchor.py"])
    out=reserve_release_dir(args.output,identity)
    refresh_build_version()
    run([str(MAKE),"-B","all","TOOLCHAIN_DIR=" + str(TOOLCHAIN)])
    run([str(MAKE),"-C","bootloader","-B","all","TOOLCHAIN_ROOT=" + str(TOOLCHAIN)])
    run([sys.executable,"tools/map_ram_guard.py","app","build/a300_firmware.map"])
    run([sys.executable,"tools/map_ram_guard.py","bootloader","bootloader/build/bootloader.map"])

    app_bin=out/f"App-{LABEL}.bin";boot_bin=out/f"Bootloader-{LABEL}.bin"
    run([str(objcopy),"-O","binary","build/a300_firmware.elf",str(app_bin)])
    shutil.copy2(ROOT/"bootloader/build/bootloader.bin",boot_bin)
    sources={
      "app_elf":ROOT/"build/a300_firmware.elf","app_hex":ROOT/"build/a300_firmware.hex","app_map":ROOT/"build/a300_firmware.map",
      "bootloader_elf":ROOT/"bootloader/build/bootloader.elf","bootloader_hex":ROOT/"bootloader/build/bootloader.hex",
      "bootloader_map":ROOT/"bootloader/build/bootloader.map"}
    boot_hex=out/f"Bootloader-{LABEL}.hex"
    shutil.copy2(sources.pop("bootloader_hex"),boot_hex)
    artifacts={"app_bin":app_bin,"bootloader_bin":boot_bin,"bootloader_hex":boot_hex}
    for key_name,source in sources.items():
        suffix=source.suffix
        name=("App" if key_name.startswith("app") else "Bootloader")+f"-{LABEL}"+suffix
        target=out/name;shutil.copy2(source,target);artifacts[key_name]=target
    app=app_bin.read_bytes();boot=boot_bin.read_bytes()
    if not 8<=len(app)<=106496 or len(boot)>24576: raise RuntimeError("firmware size outside frozen memory map")
    msp,reset=struct.unpack_from("<II",app)
    if not (0x20000000<=msp<=0x20006000 and msp%8==0 and 0x08006001<=reset<0x08020000 and reset&1): raise RuntimeError("invalid App vectors")
    package=out/f"A300-406-OTA-V{args.version_counter}.bin"
    run([sys.executable,"tools/gen_a300_ota_image.py","--input",str(app_bin),
         "--output",str(package),"--version-code",str(args.version_counter)])
    artifacts["ota_upload_bin"]=package
    combined=bytearray(b"\xFF"*(0x6000+len(app)));combined[:len(boot)]=boot;combined[0x6000:]=app
    combined_path=out/f"Combined-{LABEL}.bin";combined_path.write_bytes(combined);artifacts["combined_bin"]=combined_path
    revision=run(["git","rev-parse","HEAD"]).strip()
    # Git may emit environment warnings (for example, an unreadable global
    # excludes file). They must not invalidate an otherwise successful build.
    git_status=subprocess.run(["git","status","--porcelain"],cwd=ROOT,
                              capture_output=True,text=True,check=True)
    dirty=bool(git_status.stdout.strip())
    toolchain=run([str(TOOLCHAIN/"arm-none-eabi-gcc.exe"),"--version"]).splitlines()[0]
    report={"schema_version":1,"signing":"platform-detached","ota_format":"a300-header-v1","mcu":"N32L406CBL7",
      "memory":{"boot":[0x08000000,0x08006000],"app":[0x08006000,0x08020000]},
      "version_counter":args.version_counter,"toolchain":toolchain,"git_revision":revision,"git_dirty":dirty,
      "app_vectors":{"msp":msp,"reset":reset},
      "artifacts":{name:digest(path) for name,path in sorted(artifacts.items())}}
    manifest=out/f"SHA256SUMS-{LABEL}.json"
    manifest.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(manifest)
    return 0
if __name__=="__main__":raise SystemExit(main())
