from pathlib import Path
import difflib, hashlib, json, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]
OUT=Path(__file__).resolve().parent
files=['src/jt808.c','src/gps.c','src/mileage.c','src/gps_report_filter.c']
hashes=json.loads((OUT/'inputs.json').read_text())
changed=[f for f,h in hashes.items() if hashlib.sha256((ROOT/f).read_bytes()).hexdigest()!=h]
assert sorted(changed)==sorted(files),changed
patch=''
for f in files:
    before=OUT/(Path(f).name+'.before') if f!='src/gps_report_filter.c' else OUT/'gps_report_filter.before.c'
    patch+=''.join(difflib.unified_diff(before.read_text(encoding='utf-8').splitlines(True),(ROOT/f).read_text(encoding='utf-8').splitlines(True),fromfile='before/'+f,tofile='after/'+f))
(OUT/'changes.patch').write_text(patch,encoding='utf-8')
commands=[[sys.executable,'tools/tests/'+name+'.py'] for name in (
 'test_location_numeric_equivalence','test_gps_report_filter','test_gps_report_wire',
 'test_gps_retained_clock','test_gps_ntp_apply','test_mileage_quantization',
 'test_mileage_persistence','test_stationary_math','test_feature_guards',
 'test_stationary_location_owner')]
commands += [[sys.executable,'tools/tests/test_ram01_frame_budget.py','build-flash-audit-20260920/final']]
results=[]
for i,command in enumerate(commands):
    r=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=120)
    (OUT/f'test-{i:02d}.log').write_bytes(r.stdout)
    results.append({'command':command,'exit_code':r.returncode,'log':f'test-{i:02d}.log'})
    print(Path(command[1]).name,r.returncode,flush=True)
(OUT/'tests.json').write_text(json.dumps(results,indent=2))
(OUT/'final-inputs.json').write_text(json.dumps({f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in hashes},indent=2))
assert all(r['exit_code']==0 for r in results), 'See failed test logs'
