"""Resume packaging after capture-script snapshot race; retain completed checks."""
from pathlib import Path
script=Path(__file__).with_name('package_fix4.py')
s=script.read_text(encoding='utf-8')
exec(compile(s.split("os.environ['A300_SENSOR_WIRE']")[0],str(script),'exec'))
results=json.loads((LOG/'results.json').read_text())
snapshot=WORK/'source'
# Only this unbuilt PC utility changed during snapshot. Firmware inputs unchanged.
shutil.copy2(ROOT/'tools/capture_production_diag.ps1',snapshot/'tools/capture_production_diag.ps1')
exec(compile(s[s.index('source_hashes='):],str(script),'exec'))
