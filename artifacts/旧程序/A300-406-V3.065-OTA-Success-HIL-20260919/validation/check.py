import json, os, pathlib, subprocess, sys
ROOT=pathlib.Path(__file__).resolve().parents[2]
WORK=pathlib.Path(__file__).resolve().parent
env=os.environ.copy()
env['PYTHONUTF8']='1'
host=ROOT.parent/'tools/w64devkit/w64devkit/bin'
gcc=next((pathlib.Path(os.environ['LOCALAPPDATA'])/'Microsoft/WinGet/Packages').glob('BrechtSanders.WinLibs*/mingw64/bin/gcc.exe'))
env['PATH']=str(gcc.parent)+os.pathsep+str(host)+os.pathsep+env['PATH']
env['REQUIRE_GCC']='1'
env['CC']=str(gcc)
common=[str(host/'make.exe'),'SHELL=cmd.exe','-o','include/build_version.h','BUILD=build/ota-success-20260919/app','TOOLCHAIN_DIR='+str(ROOT/'.toolchain/bin')]
for name in sys.argv[1:]:
    cmd=common+['-j4','all'] if name=='build' else common+[name] if name in ('release-gate','ram-guard','release-guard','platform-trust-guard','flash-guard') else [sys.executable,'tools/tests/test_'+name+'.py']
    p=subprocess.run(cmd,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=300)
    (WORK/(name+'.log')).write_bytes(p.stdout)
    (WORK/(name+'.command.json')).write_text(json.dumps(dict(command=cmd,exit_code=p.returncode),indent=2))
    print(name,p.returncode,flush=True)
    if p.returncode:
        print(p.stdout.decode(errors='replace')[-2200:])
        sys.exit(p.returncode)
