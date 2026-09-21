from pathlib import Path
import importlib, os, sys, json, subprocess
root = Path(__file__).resolve().parents[1]
out = Path(__file__).resolve().parent
sys.path.insert(0, str(root/'tools/tests'))
os.environ['CC'] = str(root/'gcc.cmd')
results = {}
serial = importlib.import_module('test_at_config_serial_f39')
serial.compiler = lambda: str(root/'gcc.cmd')
serial.HARNESS = serial.HARNESS.replace('line(legacy[i]);', 'fprintf(stderr,"legacy command: %s\\n",legacy[i]);line(legacy[i]);')
for label, source in [('before', out/'before'), ('after', root)]:
    serial.ROOT = source
    results['at_config_serial_'+label] = serial.main()
numeric = importlib.import_module('test_console_numeric')
anchor = '    /* A genuinely unknown line is still reported as unknown. */'
serial.HARNESS = serial.HARNESS.replace(anchor, numeric.EXTRA + anchor, 1)
# Trace only synthetic console test commands; retain every assertion.
serial.HARNESS = serial.HARNESS.replace('line("SERVER=example.test,65535");', 'fprintf(stderr,"checking SERVER max port\\n"); line("SERVER=example.test,65535");')
serial.HARNESS = serial.HARNESS.replace('line("BSERVER=example.test,1");', 'fprintf(stderr,"checking BSERVER min port\\n"); line("BSERVER=example.test,1");')
for label, source in [('before', out/'before'), ('after', root)]:
    serial.ROOT = source
    results['console_numeric_'+label] = serial.main()
test = importlib.import_module('test_i2c_accel_int1_rearm')
test.ROOT = out/'before'
test.main()
results['i2c_trace_failure_baseline'] = 'PASS'
power = importlib.import_module('test_power_wake_routing')
power.ROOT = out/'before'
power.main()
results['power_routing_baseline'] = 'PASS'
(out/'finish-checks.json').write_text(json.dumps(results,indent=2), encoding='utf-8')
print(results)
