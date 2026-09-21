from pathlib import Path
import json, hashlib, difflib
root=Path(__file__).resolve().parents[1]
out=Path(__file__).resolve().parent
before=json.loads((out/'before.json').read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
changed=[Path(n).as_posix() for n,h in before.items() if sha(root/n)!=h]
expected_src='agnss_storage ec800m f39_config_adapter f39_reply flash_config fota fota_checkpoint gps hw_init i2c_accel jt808 power_mgr spi_flash'.split()
expected_hdr='agnss_storage ec800m flash_config fota fota_checkpoint hw_init i2c_accel jt808 spi_flash'.split()
assert set(changed)=={f'src/{n}.c' for n in expected_src}|{f'include/{n}.h' for n in expected_hdr},changed
pairs=[(n,out/'before'/n) for n in changed]
pairs += [(f'tools/tests/{p.name}',p) for p in (out/'before').glob('test_*.py')
          if sha(root/'tools/tests'/p.name)!=sha(p)]
pairs += [('tools/release_guard.py',out/'before/release_guard.py')]
diff=[];hashes={}
for name,oldpath in pairs:
    old=oldpath.read_text(encoding='utf-8')
    new=(root/name).read_text(encoding='utf-8')
    diff.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),
                                   fromfile='before/'+name,tofile='after/'+name))
    hashes[name]=sha(root/name)
    for line in difflib.ndiff(old.splitlines(),new.splitlines()):
        if line.startswith('+ '):
            assert line[2:]==line[2:].rstrip(),(name,line)
            assert not line[2:].startswith(('<<<<<<< ','>>>>>>> ')),(name,line)
for name in ('tools/tests/test_location_encoding_equivalence.py','tools/tests/test_power_wake_routing.py'):
    new=(root/name).read_text(encoding='utf-8')
    diff.extend(difflib.unified_diff([],new.splitlines(True),fromfile='/dev/null',tofile='after/'+name))
    hashes[name]=sha(root/name)
    assert all(line==line.rstrip() for line in new.splitlines()),name
(out/'task.patch').write_text(''.join(diff),encoding='utf-8')
for name in ('docs/cleanup-unused-duplicate-20260921.md','docs/superpowers/plans/2026-09-21-complete-code-cleanup.md'):
    hashes[name]=sha(root/name)
baseline=json.loads((out/'baseline/flash-capacity.json').read_text())
final=json.loads((out/'after/flash-capacity.json').read_text())
assert baseline['configuration_sha256']==final['configuration_sha256']
result={'changed_input_sha256':hashes,'same_configuration':True,
        'baseline_flash':baseline['used_bytes'],'final_flash':final['used_bytes'],
        'saved_flash':baseline['used_bytes']-final['used_bytes'],
        'remaining_flash':final['remaining_bytes'],'final_bin_sha256':final['bin_sha256'],
        'release_approved':False,'hardware_verified':False,
        'final_production_inputs_sha256':{n:sha(root/n) for n in before},
        'baseline_failures':json.loads((out/'baseline-failures.json').read_text()),
        'final_test_commands':json.loads((out/'final-tests.json').read_text()),
        'baseline_comparisons':json.loads((out/'finish-checks.json').read_text()),
        'checks':{'wire_current_and_baseline':'PASS', 'filter_96_scenarios':'PASS',
          'release_guard':'PASS after reviewed header fingerprint update',
          'release_identity_contract':'PASS','known_ram_gap_bytes':4716,
          'ram_guard':'FAIL incomplete full-program evidence',
          'flash_config_v3':'FAIL same assertion on baseline',
          'motion_corner_policy':'FAIL same assertion on baseline',
          'scope_and_added_line_whitespace':'PASS'}}
(out/'final-evidence.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'code_and_test_files':len(pairs)+2,'saved_flash':result['saved_flash'],
                  'remaining_flash':result['remaining_flash'],'scope':'PASS'}))
