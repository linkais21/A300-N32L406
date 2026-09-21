from pathlib import Path
import hashlib
import json
import difflib

root = Path(__file__).resolve().parents[1]
out = Path(__file__).resolve().parent
before = json.loads((out / 'before.json').read_text(encoding="utf-8"))
files = list(before) + ['docs/minimal-motion-filter-20260921.md',
    'docs/superpowers/plans/2026-09-21-minimal-motion-filter.md']
hashes = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files}
patch = []
for name in before:
    old = (out/Path(name).name).read_text(encoding="utf-8").splitlines(keepends=True)
    new = (root/name).read_text(encoding="utf-8").splitlines(keepends=True)
    patch.extend(difflib.unified_diff(old,new,fromfile='before/'+name,tofile='after/'+name))
for name in files:
    for i,line in enumerate((root/name).read_text(encoding="utf-8").splitlines(),1):
        assert line == line.rstrip(), (name,i,'trailing whitespace')
        assert not line.startswith(('<<<<<<< ', '>>>>>>> ')), (name,i,'conflict marker')
(out/'task.patch').write_text(''.join(patch),encoding='utf-8')
baseline=json.loads((out/'baseline/flash-capacity.json').read_text(encoding="utf-8"))
final=json.loads((out/'compact/flash-capacity.json').read_text(encoding="utf-8"))
assert baseline['configuration_sha256'] == final['configuration_sha256']
result = {'source_sha256':hashes, 'baseline_flash':baseline['used_bytes'],
    'final_flash':final['used_bytes'], 'remaining_flash':final['remaining_bytes'],
    'same_build_configuration':True, 'hardware_verified':False, 'release_approved':False,
    'checks_observed':{
      'test_gps_report_filter.py':'PASS (actual C, UBSAN)',
      'test_gps_report_wire.py':'PASS (actual filter and JT808 C)',
      'test_location_numeric_equivalence.py':'PASS',
      'test_stationary_location_owner.py':'PASS',
      'test_gps_retained_clock.py':'PASS',
      'test_gps_ntp_apply.py':'PASS',
      'test_feature_guards.py':'PASS',
      'test_ram01_frame_budget.py compact':'PASS (necessary budget only)',
      'release-guard':'PASS (gates.log)',
      'ram-guard':'FAIL: incomplete whole-program stack evidence (gates.log)',
      'size flash-guard':'PASS, LOW_HEADROOM (final-flash.log)',
      'scope whitespace/conflict check':'PASS'}}
(out/'final-evidence.json').write_text(json.dumps(result,indent=2)+'\n')
print('Recorded scoped diff, input hashes, same-configuration Flash comparison and check outcomes.')

