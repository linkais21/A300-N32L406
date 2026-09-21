from pathlib import Path
p=Path(__file__).parent
s=(p/'package_fix5.py').read_text(encoding='utf-8').replace('fix5','fix6').replace('Fix5','Fix6')
s=s.replace("'test_production_relay',", "'test_production_relay','test_relay_sms','test_remote_relay',")
s=s.replace("changed=['src/production_test.c'", "changed=['src/relay.c','include/relay.h','tools/tests/test_production_relay.py','tools/tests/test_relay_sms.py','src/production_test.c'")
s=s.replace("shutil.copy2(ROOT/'tools/capture_production_diag.ps1',OUT/'capture_production_diag.ps1')", "shutil.copy2(ROOT/'tools/capture_production_diag.ps1',OUT/'capture_production_diag.ps1')\nshutil.copy2(ROOT/'tools/capture_sensor_relay_diag.ps1',OUT/'capture_sensor_relay_diag.ps1')")
s=s.replace("'changes':['Huada", "'relay_hardware_issue':'A300 command-time GPIO reclaim ported; physical cause and actuation HIL pending','gsensor_false_pass':'unresolved; stationary/shake samples needed',\n 'changes':['A300 relay GPIO reclaim ported to N32L406 with existing polarity and safety gates','relay ODR/PAD diagnostics','Huada")
(p/'package_fix6.py').write_text(s,encoding='utf-8')
