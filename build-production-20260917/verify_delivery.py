from pathlib import Path
import hashlib
import json
import difflib
root=Path(__file__).resolve().parents[2]
fw=root/'A300-first'
tool=root/'生产测试工具/A300ProductionTester'
release=tool/'build-releases/V1.6.0-production-candidate'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for line in (release/'SHA256SUMS.txt').read_text(encoding='utf-8-sig').splitlines():
    expected,name=line.split('  ',1)
    assert sha(release/name).upper()==expected.upper(),name
revision=dict(line.split('=',1) for line in (release/'SOURCE_REVISION.txt').read_text().splitlines())
for key,name in [('protocol_sha256','src/ProductionProtocol.cs'),('application_sha256','src/A300ProductionTester.cs'),('build_script_sha256','build.ps1')]:
    assert sha(tool/name).upper()==revision[key].upper(),name
before=fw/'build-production-baseline-20260917/source-before'
changed=[]
for old in before.rglob('*'):
    if not old.is_file():continue
    rel=old.relative_to(before); current=root/rel
    if old.read_bytes()==current.read_bytes():continue
    changed.append(str(rel))
    a=old.read_text(encoding='utf-8-sig').splitlines()
    b=current.read_text(encoding='utf-8-sig').splitlines()
    for line in difflib.unified_diff(a,b):
        if line.startswith('+') and not line.startswith('+++'):
            assert line[1:].rstrip()==line[1:],(str(rel),'new trailing whitespace')
inputs=[p for folder in ['src','include','ldscript'] for p in (fw/folder).rglob('*') if p.is_file()]
inputs += [fw/'Makefile']+list((tool/'src').glob('*.cs'))+[tool/'build.ps1',tool/'config/a300_tester.ini']
manifest={'note':'Current source hashes, candidate only; RAM whole-program stack gate incomplete; no HIL or flash.',
 'inputs':{str(p.relative_to(root)):sha(p) for p in inputs},
 'outputs':{str(p.relative_to(root)):sha(p) for p in list((fw/'build-production-20260917').glob('a300_firmware.*'))+[release/'A300ProductionTester.exe']},
 'changed_from_initial_snapshots':changed}
(fw/'build-production-20260917/DELIVERY_INPUTS.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Artifact hashes, source identity and scoped added-line whitespace: PASS')
