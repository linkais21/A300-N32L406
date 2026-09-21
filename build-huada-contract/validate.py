from pathlib import Path
import hashlib
import json
import subprocess
import sys
import time

root=Path(__file__).resolve().parents[1]
out=Path(__file__).with_name('validation-final')
out.mkdir(exist_ok=True)
prefixes=('test_agnss','test_gps','test_f39','test_sms','test_at_config','test_fota',
          'test_remote_relay','test_relay_sms','test_ext_flash','test_feature',
          'test_release_guard','test_release_identity','test_work_mode','test_production',
          'test_ec800m','test_platform_trust','test_status_led','test_jt808','test_blind_zone','test_adc','test_debug',
          'test_boot','test_terminal_identity')
files=[p for d in ('src','include','tools/tests','bootloader/src','bootloader/include') for p in (root/d).rglob('*') if p.is_file() and p.suffix in ('.c','.h','.py','.s')]
(out/'input-hashes.json').write_text(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},indent=2),encoding='utf-8')
results=[]
for p in sorted((root/'tools/tests').glob('test_*.py')):
    if not p.name.startswith(prefixes):continue
    cmd=[sys.executable,'-B',str(p)]
    started=time.monotonic()
    try:
        r=subprocess.run(cmd,cwd=root,capture_output=True,timeout=150)
        (out/(p.stem+'.log')).write_bytes(r.stdout+r.stderr)
        code=r.returncode
    except subprocess.TimeoutExpired as e:
        (out/(p.stem+'.log')).write_bytes((e.stdout or b'')+(e.stderr or b''))
        code=124
    results.append({'test':p.name,'command':cmd,'exit_code':code,'seconds':round(time.monotonic()-started,2)})
    (out/'commands.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    if code:print('FAIL',p.name,code,flush=True)
print('RESULT',len(results),'tests;',sum(x['exit_code']!=0 for x in results),'failed',flush=True)
raise SystemExit(any(x['exit_code']!=0 for x in results))
