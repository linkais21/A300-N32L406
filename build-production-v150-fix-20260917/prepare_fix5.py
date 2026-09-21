from pathlib import Path
p=Path(__file__).parent
s=(p/'package_fix4.py').read_text(encoding='utf-8')
s=s.replace('fix4','fix5').replace('Fix4','Fix5')
s=s.replace("'test_production_test','test_production_gnss',", "'test_gps_huada_output','test_gps_huada_gsv','test_production_test','test_production_gnss',")
s=s.replace("'gps_hardware_cn_issue':'unresolved; bounded diagnostic capture included'", "'gps_hardware_cn_issue':'CFG-MSG and dual-band parsing corrected against vendor protocol/samples; HIL pending'")
s=s.replace("'changes':['Gsensor", "'changes':['Huada F1D9 CFG-MSG init and wake','Huada cross-band GSV page parsing without duplicate band counting','Gsensor")
(p/'package_fix5.py').write_text(s,encoding='utf-8')
