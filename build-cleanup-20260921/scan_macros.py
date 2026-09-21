from pathlib import Path
import re,collections,json
root=Path(__file__).resolve().parents[1]
rows=[]
for p in sorted((root/'src').glob('*.c')):
    s=p.read_text(encoding='utf-8')
    counts=collections.Counter(re.findall(r'\b\w+\b',s))
    for name in re.findall(r'^#define\s+(\w+)',s,re.M):
        if counts[name]==1:rows.append([p.name,name])
print(json.dumps(rows,indent=2))
