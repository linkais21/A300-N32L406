from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'tools/experiments'))
import firmware_size_trial as trial
p=root/'src/mileage.c'
s=trial.quantization_source(trial.math_source(p.read_text(encoding='utf-8'),'bounded'))
s=trial.log_source(s,'src/mileage.c')
s=s.replace('/* Trial only: bounded double-precision distance','/* Bounded double-precision distance').replace('Experimental policy:','Mileage policy:')
p.write_text(s,encoding='utf-8')
p=root/'src/jt808.c'
p.write_text(trial.log_source(p.read_text(encoding='utf-8'),'src/jt808.c'),encoding='utf-8')
