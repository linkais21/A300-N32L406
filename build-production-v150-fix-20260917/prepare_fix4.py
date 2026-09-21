from pathlib import Path
p=Path(__file__).parent
s=(p/'package_fix3.py').read_text(encoding='utf-8')
s=s.replace('fix3','fix4').replace('Fix3','Fix4')
s=s.replace("os.environ['A300_V150_WIRE']", "os.environ['A300_SENSOR_WIRE']=str(WORK/'sensor-wire.txt')\nrun('sensor-wire',[sys.executable,'tools/tests/test_production_test.py','--wire-output',WORK/'sensor-wire.txt'])\nos.environ['A300_V150_WIRE']")
s=s.replace("'test_production_test','test_production_gnss',", "'test_production_test','test_production_gnss','test_nmea_replay','test_gps_drop_diagnostics','test_gps_tx_bounded','test_gps_ntp_apply','test_production_adc','test_production_relay',")
s=s.replace("changed=['Makefile'", "run('terminal-identity-known-failure',[sys.executable,'tools/tests/test_terminal_identity.py'],allowed=(1,))\nchanged=['src/production_test.c','src/gps.c','include/gps.h','tools/tests/test_production_test.py','tools/tests/test_production_gnss.py','tools/tests/test_v150_binary.ps1','Makefile'")
s=s.replace("shutil.copytree(LOG,OUT/'validation')", "shutil.copytree(LOG,OUT/'validation')\nshutil.copy2(WORK/'sensor-wire.txt',OUT/'validation/sensor-wire.txt')\nshutil.copy2(ROOT/'tools/capture_production_diag.ps1',OUT/'capture_production_diag.ps1')")
s=s.replace("'changes':['APN", "'known_test_failure':'terminal identity fixture missing dependencies', 'gps_hardware_cn_issue':'unresolved; bounded diagnostic capture included',\n 'changes':['Gsensor INT field for original EXE','SOS LEVEL and ACTIVE for original EXE','bounded GNSS trace and counters','APN")
(p/'package_fix4.py').write_text(s,encoding='utf-8')
