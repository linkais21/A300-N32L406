from pathlib import Path
import re, json, collections, sys
root=Path(__file__).resolve().parents[1]
out=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'tools'))
from release_guard import strip_c_comments
sources=sorted((root/'src').glob('*.c'))
texts={p:strip_c_comments(p.read_text(encoding='utf-8')) for p in sources}
words=collections.Counter(re.findall(r'\b\w+\b','\n'.join(texts.values())))
host='\n'.join(p.read_text(encoding='utf-8',errors='replace') for p in (root/'tools/tests').glob('*') if p.is_file())
assembly='\n'.join(p.read_text(encoding='utf-8') for p in (root/'src').glob('*.s'))
rows=[];inventory=[]
for p,s in texts.items():
    names=[]
    for m in re.finditer(r'^([\w *]+?)\b(\w+)\s*\([^;{}]*\)\s*\{',s,re.M):
        prefix,name=m.group(1),m.group(2)
        if name in ('if','while','for','switch'):continue
        names.append(name)
        if words[name]==1:
            if name in assembly or name in ('_write','_read','_close','_fstat','_isatty','_lseek','_getpid','_kill'):
                kind='startup/IRQ/libc ABI'
            elif re.search(r'\b'+name+r'\b',host):kind='host test or diagnostic contract'
            else:kind='REVIEW'
            rows.append({'file':p.name,'symbol':name,'reason':kind})
    inventory.append({'file':p.name,'definitions_scanned':len(names)})
result={'modules':inventory,'single_reference_definitions':rows,
        'note':'Identifier scan is a review aid, not proof of dead code; compiler/link and call sites reviewed separately.'}
(out/'source-inventory.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print('C modules:',len(inventory),'definitions:',sum(r['definitions_scanned'] for r in inventory))
print(json.dumps([r for r in rows if r['reason']=='REVIEW'],indent=2))
