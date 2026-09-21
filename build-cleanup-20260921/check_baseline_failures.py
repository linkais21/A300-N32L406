from pathlib import Path
import sys, importlib, json, os
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'tools/tests'))
os.environ['CC']=str(root/'gcc.cmd')
results={}
for name in ('test_flash_config_v3','test_motion_corner_policy'):
    test=importlib.import_module(name)
    test.ROOT=root/'build-cleanup-20260921/before'
    try:
        result=test.main()
        results[name]={'exit':result}
    except AssertionError as exc:
        results[name]={'exit':1,'failure':str(exc)}
    print(name,results[name])
(root/'build-cleanup-20260921/baseline-failures.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
sys.exit(1 if any(r['exit'] for r in results.values()) else 0)
