from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'tools'))
import release_guard as guard
name='include/jt808.h'
before=(root/'build-cleanup-20260921/before'/name).read_text(encoding='utf-8')
after=(root/name).read_text(encoding='utf-8')
assert after == before.replace('uint16_t jt808_get_heartbeat_s(void);\n','')
assert guard.canonical_file_digest(before,name)=='b5e5bb725e1439b3d6c60c3d79cfb6484d6a2c3d5ecdb1df2c431d0aecafe02a'
print(guard.canonical_file_digest(after,name))
