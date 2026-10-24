from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];WORK=Path(__file__).resolve().parent
baseline=json.loads((ROOT/'build-v3093-delivery/selected-host-tests.json').read_text(encoding='utf-8'))
extra=['test_build_version_refresh.py','test_gps_date_coherence.py','test_ntp_sleep_clock.py',
       'test_rtc_lsi_calibration.py','test_sleep_monotonic_wrap.py','test_nmea_replay.py',
       'test_sleep_location_reporting.py','test_jt808_protocol_edges.py','test_hardfault_frame.py',
       'test_ec800m_stalled_tick.py','test_ec800m_udp_transaction.py','test_tcp_long_offline.py',
       'test_sms_ingress.py','test_sms_whitelist.py','test_sms_execute_boundary.py',
       'test_jt808_text_command.py','test_text_ack_order.py','test_log_platform_wire.py',
       'test_cfg_query_pass.py','test_cfg_query_lifetime.py','test_work_mode_policy.py',
       'test_motion_corner_policy.py','test_corner_blind_zone_replay.py','test_agnss_online.py',
       'test_agnss_snapshot.py','test_agnss_storage.py','test_agnss_workspace_ownership.py']
tests=list(dict.fromkeys(baseline+extra))
(WORK/'selected-host-tests.json').write_text(json.dumps(tests,indent=2)+'\n',encoding='utf-8')
logs=WORK/'host-logs';logs.mkdir(exist_ok=False)
paths=[]
for d in ['src','include','tools','bootloader/src','bootloader/include','ldscript','bootloader/ldscript']:
    paths.extend(p for p in (ROOT/d).rglob('*') if p.is_file() and p.suffix in {'.c','.h','.py','.json','.s','.ld'})
paths += [ROOT/'Makefile',ROOT/'bootloader/Makefile',ROOT/'release_identity.json']
def hashes():return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}
before=hashes();results=[]
for i,name in enumerate(tests,1):
    command=[sys.executable,'tools/tests/'+name]
    adaptation=None
    if name=='test_ram_release_budget.py':command+=['build-v3094-delivery/app']
    if name=='test_factory_init_artifact.py':
        # Same production-image check, pointed at the isolated current artifacts.
        original=(ROOT/'tools/tests'/name).read_text(encoding='utf-8')
        original=original.replace('ROOT = Path(__file__).resolve().parents[2]',f'ROOT = Path({str(ROOT)!r})')
        original=original.replace('ROOT / "bootloader" / "build"',f'Path({str(WORK/"boot")!r})')
        tc=ROOT.parents[2]/'A300_Tools/toolchains/arm-gnu-toolchain-14.3.rel1/bin'
        original=original.replace('ROOT / ".toolchain" / "bin"',f'Path({str(tc)!r})')
        adapted=WORK/'factory_init_current_artifact.py';adapted.write_text(original,encoding='utf-8')
        command=[sys.executable,str(adapted)];adaptation='Output/tool paths only; assertions unchanged.'
    start=time.monotonic()
    try:
        r=subprocess.run(command,cwd=ROOT,capture_output=True,timeout=240);data=r.stdout+r.stderr;code=r.returncode
    except subprocess.TimeoutExpired as e:
        data=(e.stdout or b'')+(e.stderr or b'')+b'\nTIMEOUT\n';code=124
    (logs/(Path(name).stem+'.log')).write_bytes(data)
    results.append({'test':name,'command':command,'exit_code':code,'elapsed_s':round(time.monotonic()-start,3),
                    'log':'host-logs/'+Path(name).stem+'.log','adaptation':adaptation})
    (WORK/'host-results.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
    print(f'[{i}/{len(tests)}] {name}: '+('PASS' if code==0 else f'FAIL exit={code}'),flush=True)
    if code:print(data.decode('utf-8',errors='replace')[-4000:],flush=True)
after=hashes();assert before==after,'Source changed during verification'
identity=json.loads((ROOT/'release_identity.json').read_text(encoding='utf-8'))
record={'verified_at_utc':datetime.now(timezone.utc).isoformat(),'version':identity['firmware_version'],
        'source_sha256':after,'tests_passed':sum(r['exit_code']==0 for r in results),
        'tests_failed':sum(r['exit_code']!=0 for r in results),'tests_skipped':0}
(WORK/'source-identity.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
print(f"Results: {record['tests_passed']} passed, {record['tests_failed']} failed",flush=True)
raise SystemExit(1 if record['tests_failed'] else 0)
