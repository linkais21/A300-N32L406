"""BUILD-01: exercise incremental builds with the production Makefile/ARM GCC."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
MAKE = os.environ.get("A300_MAKE") or shutil.which("make.exe") or str(
    ROOT.parent / "tools/w64devkit/w64devkit/bin/make.exe")
TOOLCHAIN = Path(os.environ.get("A300_TOOLCHAIN_DIR", ROOT / ".toolchain/bin"))


class DependencyTests(unittest.TestCase):
    def test_incremental_headers_flags_and_missing_dependencies(self):
        with tempfile.TemporaryDirectory(prefix="build01_") as directory:
            work = Path(directory)
            shutil.copy2(ROOT / "Makefile", work / "Makefile")
            for name in ("include", "src", "sdk", "third_party/micro-ecc"):
                (work / name).mkdir(parents=True)
            (work / "include/trusted_public_key.h").write_text("\n")
            (work / "include/inner.h").write_text("#define VALUE 7\n")
            (work / "include/outer.h").write_text('#include "inner.h"\n')
            sources = ["src/probe.c", "sdk/probe.c", "src/firmware_signature.c",
                       "third_party/micro-ecc/uECC.c", "src/start.s"]
            for index, source in enumerate(sources):
                body = (f"int probe{index}(void){{return VALUE;}}\n" if source.endswith(".c")
                        else ".section .rodata\n.word VALUE\n")
                (work / source).write_text('#include "outer.h"\n' + body)
            (work / "src/unrelated.c").write_text("int unrelated(void){return 1;}\n")
            sources.append("src/unrelated.c")
            objects = ["build/" + str(Path(s).with_suffix(".o")).replace("\\", "/")
                       for s in sources]
            common = [MAKE, "-j4", f"TOOLCHAIN_DIR={TOOLCHAIN.as_posix()}",
                      "C_SRCS=" + " ".join(s for s in sources if s.endswith(".c")),
                      "ASM_SRCS=src/start.s"]

            def run(*options):
                def snapshot():
                    return {p.relative_to(work): p.stat().st_mtime_ns
                            for p in work.rglob("*") if p.is_file()}

                before_dry_run = snapshot() if "-n" in options else None
                result = subprocess.run(common + list(options) + objects, cwd=work,
                                        capture_output=True, text=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                if before_dry_run is not None:
                    self.assertEqual(before_dry_run, snapshot(), "dry-run modified files")
                return result.stdout

            def times():
                return [(work / p).stat().st_mtime_ns for p in objects]

            run()
            before = times()
            self.assertNotIn(" -c ", run("-n"))
            run()
            self.assertEqual(before, times(), "unchanged build recompiled objects")
            planned = run("-n", "-W", "include/inner.h")
            for source in sources[:-1]:
                self.assertIn(f"-c {source} ", planned, "transitive header edit was ignored")
            self.assertNotIn("-c src/unrelated.c ", planned)
            # Windows make compares timestamps at one-second resolution.
            time.sleep(1.1)
            (work / "include/inner.h").write_text("#define VALUE 9\n")
            run()
            self.assertTrue(all(a != b for a, b in zip(before[:-1], times()[:-1])))
            self.assertEqual(before[-1], times()[-1])
            # Each probe must change the effective flags; the production default is -g3.
            for flags in ("EXTRA_CFLAGS=-DBUILD01_PROBE=1", "EXTRA_CFLAGS=",
                          "DEBUG_FLAGS=-g1", "SDK_CFLAGS=-Wno-unused-parameter",
                          "SIGNATURE_CFLAGS=-fno-lto -g1",
                          "ASFLAGS=-mcpu=cortex-m4 -mthumb -x assembler-with-cpp -Iinclude",
                          "LDFLAGS=-nostdlib", "EXTRA_CFLAGS="):
                before = times()
                self.assertIn("-c src/probe.c ", run("-n", flags))
                run(flags)
                self.assertTrue(all(a != b for a, b in zip(before, times())))
                self.assertNotIn(" -c ", run("-n", flags))
            # Lost depfile (including an old build made before BUILD-01) repairs itself.
            (work / "build/src/probe.d").unlink()
            self.assertIn("-c src/probe.c ", run("-n"))
            run()
            self.assertTrue((work / "build/src/probe.d").is_file())
            # Removing an obsolete include must not leave a fatal stale prerequisite.
            time.sleep(1.1)
            (work / "include/outer.h").write_text("#define VALUE 11\n")
            (work / "include/inner.h").unlink()
            run()
            self.assertNotIn(" -c ", run("-n"))


if __name__ == "__main__":
    unittest.main()
