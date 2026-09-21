from pathlib import Path
import re,shutil
root=Path(__file__).resolve().parents[1]
removals={
 'src/ec800m.c':['UDP_TXN_OPEN','UDP_TXN_SEND','UDP_TXN_CLOSE'],
 'src/flash_config.c':['SLOT_CURRENT_TOTAL'],
 'src/i2c_accel.c':['DA218E_REG_ACC_X_MSB','DA218E_REG_ACC_Y_LSB','DA218E_REG_ACC_Y_MSB',
                    'DA218E_REG_ACC_Z_LSB','DA218E_REG_ACC_Z_MSB',
                    'VIBRATION_SENSITIVITY_LEVEL_10','VIBRATION_SENSITIVITY_LEVEL_COUNT'],
}
for name,names in removals.items():
    p=root/name;s=p.read_text(encoding='utf-8')
    for macro in names:
        s,n=re.subn(r'^#define\s+'+macro+r'\b[^\n]*\n','',s,flags=re.M)
        assert n==1,(name,macro,n)
    p.write_text(s,encoding='utf-8',newline='\n')
for name in ('test_i2c_accel_vibration_adapter.py','test_i2c_accel_int1_rearm.py'):
    p=root/'tools/tests'/name;shutil.copy2(p,root/'build-cleanup-20260921/before'/name)
p=root/'tools/tests/test_i2c_accel_vibration_adapter.py'
s=p.read_text(encoding='utf-8')
s=s.replace('require(r"VIBRATION_SENSITIVITY_LEVEL_10", SOURCE,\n            "level 10 must be represented as a named product-level mapping")',
            'require(r"VIBRATION_SENSITIVITY_MIN.*VIBRATION_SENSITIVITY_MAX", SOURCE,\n            "product-level mapping must retain its supported bounds")')
for reg,val in [('INT_LATCH','0x07U'),('INT_SET1','0x83U'),('INT_MAP1','0x04U'),('ACTIVE_THS','0x26U')]:
    s=s.replace('i2c_write_reg\\(DA218E_REG_'+reg+',\\s*'+val+'\\)',
                '\\{DA218E_REG_'+reg+',\\s*'+val+'\\}')
p.write_text(s,encoding='utf-8',newline='\n')
