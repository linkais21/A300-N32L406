from pathlib import Path
import subprocess, sys, json
root=Path(__file__).resolve().parents[1]
out=Path(__file__).resolve().parent
names='gps_report_wire gps_report_filter nmea_replay gps_huada_gsv gps_retained_clock f39_config f39_actions f39_end_to_end car_reply_encoding at_config_serial_f39 i2c_accel_int1_rearm i2c_accel_vibration_adapter i2c_accel_vibration_filter vibration_sensitivity power_wake_routing fota_checkpoint_powercut agnss_storage ext_flash_store_host feature_guards stationary_location_owner corner_blind_zone_replay release_identity_contract shallow_sleep_contract sleep_wake_timestamp_vibration_contract'.split()
commands=[[sys.executable, f'tools/tests/test_{n}.py'] for n in names]
commands.append([sys.executable,'tools/tests/test_location_encoding_equivalence.py','--baseline',str(out/'before/src/jt808.c')])
results=[]
for i,cmd in enumerate(commands):
    p=subprocess.run(cmd,cwd=root,capture_output=True,text=True,errors='replace',timeout=180)
    log=out/(Path(cmd[1]).stem+'.log')
    log.write_text(p.stdout+p.stderr,encoding='utf-8')
    results.append({'command':cmd,'exit':p.returncode,'log':log.name})
    print(Path(cmd[1]).stem,p.returncode,flush=True)
    if p.returncode: print((p.stdout+p.stderr)[-1800:],flush=True)
(out/'final-tests.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
sys.exit(any(r['exit'] for r in results))
