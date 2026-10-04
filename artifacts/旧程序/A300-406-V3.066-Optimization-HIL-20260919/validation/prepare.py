from pathlib import Path
import hashlib, json, re, shutil, subprocess, sys

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_dev_release import refresh_build_version
import release_guard

changed = ['release_identity.json', 'include/build_version.h', 'include/config.h',
           'tools/release_guard.py', 'tools/tests/test_release_identity_contract.py']
before = WORK / 'before'
before.mkdir(exist_ok=False)
for name in changed:
    p = before / name
    p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / name, p)
identity = json.loads((ROOT / 'release_identity.json').read_text())
assert identity['firmware_version_counter'] == 3065
identity.update(firmware_revision=66, firmware_version_counter=3066,
                firmware_version=identity['firmware_version'].replace('V3.065', 'V3.066'))
(ROOT / 'release_identity.json').write_text(json.dumps(identity, indent=2) + '\n')
refresh_build_version()
p = ROOT / 'tools/tests/test_release_identity_contract.py'
s = p.read_text(encoding='utf-8').replace('065', '066').replace('3065', '3066').replace('"firmware_revision": 65', '"firmware_revision": 66')
p.write_text(s, encoding='utf-8')
p = ROOT / 'tools/release_guard.py'
s = p.read_text(encoding='utf-8').replace('Reviewed: V3.065 identity/counter only', 'Reviewed: V3.066 identity/counter only')
for name in ['include/config.h', 'include/build_version.h']:
    old = release_guard.CANONICAL_IDENTITY_FILE_SHA256[name]
    new = release_guard.canonical_file_digest((ROOT / name).read_text(encoding='utf-8'), name)
    assert s.count(old) == 1
    s = s.replace(old, new)
p.write_text(s, encoding='utf-8')
# Freeze source inputs, including the SDK used by the isolated Boot build.
snapshot = WORK / 'source'
snapshot.mkdir(exist_ok=False)
for directory in ['src', 'include', 'tools', 'ldscript', 'sdk', 'third_party', 'bootloader']:
    shutil.copytree(ROOT / directory, snapshot / directory,
                    ignore=shutil.ignore_patterns('__pycache__', 'build', '*.pyc'))
for name in ['Makefile', 'release_identity.json']:
    shutil.copy2(ROOT / name, snapshot / name)
hashes = {p.relative_to(snapshot).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in snapshot.rglob('*') if p.is_file()}
(WORK / 'source-hashes.json').write_text(json.dumps(hashes, indent=2))
print(json.dumps(identity))
