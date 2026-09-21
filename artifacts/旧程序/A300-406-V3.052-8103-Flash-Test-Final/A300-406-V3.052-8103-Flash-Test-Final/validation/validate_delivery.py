from pathlib import Path
import json, subprocess, sys, shutil
ROOT=Path(__file__).resolve().parents[2]
work=ROOT/'build/params-size-3052'
tests=['test_jt808_params','test_jt808_params_wire','test_jt808_dual_session',
 'test_flash_config_v3','test_flash_config_migration','test_f39_config','test_f39_dualset',
 'test_f39_end_to_end','test_at_config_handoff','test_mileage_persistence',
 'test_mileage_quantization','test_size_trial','test_release_identity_contract',
 'test_boot_cold_start_recovery','test_bootloader_bcr_failclosed','test_platform_trust_anchor',
 'test_feature_guards','test_ext_flash_layout','test_agnss_workspace_ownership',
 'test_fota_package','test_dev_release_manifest']
results=[]
for name in tests:
    command=[sys.executable,'tools/tests/'+name+'.py']
    r=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (work/(name+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
    results.append(dict(test=name,exit_code=r.returncode,command=command))
    print(name,r.returncode,flush=True)
(work/'tests-final.json').write_text(json.dumps(results,indent=2))
raise SystemExit(1 if any(r['exit_code'] for r in results) else 0)
