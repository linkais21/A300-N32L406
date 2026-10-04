from pathlib import Path
import hashlib, json, shutil, zipfile
WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
OUT = ROOT / 'artifacts/A300-406-V3.066-Optimization-HIL-20260919'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

# Resume only the archive step after exclusive creation rejected a pre-existing
# incorrectly shortened ZIP name. Firmware and earlier validation remain intact.
for line in (OUT / 'SHA256SUMS.txt').read_text().splitlines():
    digest, name = line.split('  ', 1)
    assert sha(OUT / name) == digest, name
(WORK / 'packaging-recovery.json').write_text(json.dumps(dict(
    initial_exit_code=1, reason='Path.with_suffix shortened the dotted version directory; exclusive creation rejected existing A300-406-V3.zip',
    recovery='Append .zip to complete directory name; verify existing candidate hashes and archive without rebuilding or overwriting old artifacts.'), indent=2))
for n in ['package.py', 'finalize.py', 'packaging-recovery.json']:
    shutil.copy2(WORK / n, OUT / 'validation' / n)
files = sorted(p for p in OUT.rglob('*') if p.is_file() and p.name != 'SHA256SUMS.txt')
(OUT / 'SHA256SUMS.txt').write_text(''.join(sha(p) + '  ' + p.relative_to(OUT).as_posix() + '\n' for p in files))
archive = OUT.parent / (OUT.name + '.zip')
with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
    for p in OUT.rglob('*'):
        if p.is_file(): z.write(p, OUT.name + '/' + p.relative_to(OUT).as_posix())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for line in (OUT / 'SHA256SUMS.txt').read_text().splitlines():
        digest, name = line.split('  ', 1)
        assert sha(OUT / name) == digest
        assert hashlib.sha256(z.read(OUT.name + '/' + name)).hexdigest() == digest
archive.with_suffix('.zip.sha256').write_text(sha(archive) + '  ' + archive.name + '\n')
print(json.dumps(dict(package=str(archive), zip_sha256=sha(archive),
                     manifest=json.loads((OUT / 'manifest.json').read_text())), indent=2))
