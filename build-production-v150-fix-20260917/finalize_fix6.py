"""Exclude local device captures from the shareable source snapshot."""
from pathlib import Path
import hashlib,json,shutil,zipfile
root=Path(__file__).resolve().parents[1]
old=root/'artifacts/A300-406-V3.054-V150-Fix6-20260917'
out=root/'artifacts/A300-406-V3.054-V150-Fix6-Final-20260917'
assert not out.exists()
shutil.copytree(old,out,ignore=shutil.ignore_patterns('diagnostic-logs','SHA256SUMS.txt'))
m=json.loads((out/'MANIFEST.json').read_text())
m['source_hashes']={k:v for k,v in m['source_hashes'].items() if 'diagnostic-logs/' not in k}
m['excluded_runtime_data']='tools/diagnostic-logs (device captures are not build inputs)'
(out/'MANIFEST.json').write_text(json.dumps(m,indent=2)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for k,v in m['source_hashes'].items():assert sha(out/'source'/k)==v,k
assert (out/'SWD-Combined-N32L406CBL7.bin').read_bytes()==(old/'SWD-Combined-N32L406CBL7.bin').read_bytes()
lines=[sha(p)+'  '+p.relative_to(out).as_posix() for p in sorted(out.rglob('*')) if p.is_file()]
(out/'SHA256SUMS.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
archive=Path(str(out)+'.zip')
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
 for p in out.rglob('*'):
  if p.is_file():z.write(p,p.relative_to(out.parent))
with zipfile.ZipFile(archive) as z:
 assert z.testzip() is None
 assert not any('diagnostic-logs/' in n for n in z.namelist())
Path(str(archive)+'.sha256').write_text(sha(archive)+'  '+archive.name+'\n')
print('Verified final package',archive,'build',m['build_stamp'],'free',m['app_free_bytes'])
