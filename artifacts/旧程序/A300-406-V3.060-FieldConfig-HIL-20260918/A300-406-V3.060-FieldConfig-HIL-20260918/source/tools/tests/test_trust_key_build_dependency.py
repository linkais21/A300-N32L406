"""A trust-header edit must rebuild every App/Bootloader trust consumer."""
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_key_rebuilds():
    make = shutil.which("make.exe") or str(ROOT.parent / "tools/w64devkit/w64devkit/bin/make.exe")
    cases = [("Makefile", "src/firmware_signature.c", "build/src/firmware_signature.o", "include/trusted_public_key.h"),
             ("Makefile", "src/fota.c", "build/src/fota.o", "include/trusted_public_key.h"),
             ("bootloader/Makefile", "../src/firmware_signature.c", "build/firmware_signature.o", "../include/trusted_public_key.h"),
             ("bootloader/Makefile", "src/image_verify.c", "build/image_verify.o", "../include/trusted_public_key.h")]
    with tempfile.TemporaryDirectory(prefix="trust_deps_") as directory:
        temp = Path(directory)
        for index, (makefile, source, target, header) in enumerate(cases):
            work = temp / str(index) / "work"
            work.mkdir(parents=True)
            shutil.copyfile(ROOT / makefile, work / "Makefile")
            now = time.time()
            for relative, age in [(source, 20), (header, 20), (target, 10)]:
                path = work / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="ascii")
                os.utime(path, (now-age, now-age))
            result = subprocess.run([make, "-n", "-W", header, target], cwd=work,
                                    capture_output=True, text=True)
            assert result.returncode == 0, result.stdout + result.stderr
            assert f"-c {source} " in result.stdout, f"{makefile}: stale key retained in {target}: {result.stdout}"


if __name__ == "__main__":
    test_key_rebuilds()
    print("test_trust_key_build_dependency: PASS")
