from pathlib import Path
import re, json, hashlib, shutil
root=Path(__file__).resolve().parents[1]
out=Path(__file__).resolve().parent
files=[*root.glob('src/*.[ch]'),*root.glob('include/*.[ch]'),root/'Makefile']
hashes={}
for p in files:
    rel=p.relative_to(root)
    dest=out/'before'/rel
    if not dest.exists():
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,dest)
    hashes[str(rel)]=hashlib.sha256(dest.read_bytes()).hexdigest()
(out/'before.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
src='\n'.join(p.read_text(encoding='utf-8',errors='replace') for p in root.glob('src/*.[ch]'))
for p in root.glob('src/*.c'):
    s=p.read_text(encoding='utf-8',errors='replace')
    for m in re.finditer(r'^([\w *]+?)\b(\w+)\s*\([^;{}]*\)\s*\{',s,re.M):
        prefix,name=m.group(1),m.group(2)
        if name in ('if','while','for','switch'): continue
        n=len(re.findall(r'\b'+name+r'\b',src))
        if n==1 and 'static' not in prefix:
            print(f'{p.name}:{s[:m.start()].count(chr(10))+1}: {name}')
