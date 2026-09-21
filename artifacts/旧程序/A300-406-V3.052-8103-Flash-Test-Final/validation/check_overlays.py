from pathlib import Path
import json, shutil, subprocess,sys
ROOT=Path(__file__).resolve().parents[2];WORK=ROOT/'build/params-size-3052'
shadow=WORK/'final-overlay-host';shadow.mkdir(exist_ok=False)
for name in ['src','include','tools']:shutil.copytree(ROOT/name,shadow/name)
for name in ['jt808.c','mileage.c']:shutil.copy2(ROOT/'build/params-size-final-3052/combined/sources'/name,shadow/'src'/name)
tests=['test_jt808_params','test_jt808_params_wire','test_jt808_dual_session','test_mileage_persistence',
       'test_ec800m_qisend','test_ec800m_urc','test_ec800m_dma_rx','test_ec800m_recovery',
       'test_ec800m_health','test_ec800m_udp','test_jt808_session_send_failure','test_log_platform','test_production_selftest']
results=[]
for name in tests:
    p=shadow/'tools/tests'/(name+'.py')
    if not p.exists():continue
    r=subprocess.run([sys.executable,str(p)],cwd=shadow,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (WORK/('overlay-'+name+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
    results.append(dict(test=name,exit_code=r.returncode));print(name,r.returncode,flush=True)
(WORK/'overlay-tests.json').write_text(json.dumps(results,indent=2))
assert not any(r['exit_code'] for r in results)
