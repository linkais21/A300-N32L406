from pathlib import Path
import re
root=Path(__file__).resolve().parents[1]
for rel in ('src/i2c_accel.c','include/i2c_accel.h'):
    path=root/rel
    s=path.read_bytes().decode('utf-8')
    if rel.startswith('src'):
        start=s.index('bool i2c_accel_detect_vibration(void)')
        end=s.index('void i2c_accel_reset_vibration_window',start)
        s=s[:start]+s[end:]
        s=re.sub(r'^#define VIB_CONFIRM[^\r\n]*\r?\n','',s,flags=re.M)
        start=s.index('/* G452-compatible adaptive baseline')
        end=s.index('#define VIB_THRESH',start)
        s=s[:start]+'/* Shared adaptive baseline threshold for the active work-mode detector. */\n'+s[end:]
    else:
        s=re.sub(r'^bool\s+i2c_accel_(?:detect_vibration|is_moving)\(void\);[^\r\n]*\r?\n','',s,flags=re.M)
    path.write_bytes(s.encode('utf-8'))
