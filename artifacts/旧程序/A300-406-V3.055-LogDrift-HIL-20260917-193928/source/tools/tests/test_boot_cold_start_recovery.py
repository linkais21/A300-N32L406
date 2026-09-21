"""Run production BCR + main against the observed zero-read cold-start fault."""
from pathlib import Path
import importlib.util
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("failclosed", Path(__file__).with_name("test_bootloader_bcr_failclosed.py"))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

HARNESS = base.HARNESS[:base.HARNESS.index("int main(int argc")]
HARNESS = HARNESS.replace("static jmp_buf done;", r'''
static jmp_buf done;
static unsigned waits, zero_until, io_until;
void boot_bcr_retry_wait(uint32_t attempt, bool io_error)
{ (void)io_error; assert(attempt == ++waits); assert(waits < 20U); }
void boot_startup_status(const char *stage, int32_t value)
{ (void)stage; (void)value; }
''').replace("++reads[slot];", r'''
    ++reads[slot];
    if (waits < io_until) return false;
    if (waits < zero_until) { memset(data, 0, length); return true; }
''')
HARNESS += r'''
int main(int argc, char **argv)
{
    assert(argc == 2);
    unsigned scenario = strtoul(argv[1], NULL, 10);
    memset(slots, 0xff, sizeof slots);
    unsigned expected_waits = 0;
    bool should_jump = false;
    switch (scenario) {
    case 0: zero_until=5; expected_waits=5; should_jump=true; break;
    case 1: io_until=3; expected_waits=3; should_jump=true; break;
    case 2: zero_until=100; expected_waits=19; break;
    case 3: io_until=100; expected_waits=19; break;
    case 4: zero_until=19; expected_waits=19; should_jump=true; break;
    case 5: should_jump=true; break;
    case 6: seed(0,8,BCR_ACTIVE); seed(1,9,BCR_PENDING); read_fail=2; expected_waits=19; break;
    case 7: seed(0,8,BCR_ACTIVE); zero_until=4; expected_waits=4; should_jump=true; break;
    case 8: memset(slots,0x37,sizeof slots); expected_waits=19; break;
    default: assert(0);
    }
    if (!setjmp(done)) (void)bootloader_main();
    if (jumps != (unsigned)should_jump || waits != expected_waits) {
        fprintf(stderr,"cold-start scenario=%u jumps=%u expected=%u waits=%u expected=%u\n",
                scenario,jumps,should_jump,waits,expected_waits);
        return 1;
    }
    assert(!writes && !erases);
    assert(reads[0] == reads[1] && reads[0] <= 20U);
    return 0;
}
'''

def main():
    compiler = shutil.which("gcc") or shutil.which("clang")
    assert compiler
    with tempfile.TemporaryDirectory(prefix="cold_start_") as directory:
        p=Path(directory)
        platform=(ROOT/"bootloader/src/platform_n32l406.c").read_text(encoding="utf-8")
        counter=platform[platform.index("bool boot_rollback_counter"):platform.index("void boot_jump_to")]
        (p/"h.c").write_text(HARNESS+counter,encoding="ascii")
        common=[compiler,"-std=c99","-O1","-Wall","-Wextra","-Werror",
                "-I",str(ROOT/"bootloader/include"),"-I",str(ROOT/"include")]
        subprocess.run(common+["-Dmain=bootloader_main","-c",str(ROOT/"bootloader/src/main.c"),"-o",str(p/"main.o")],check=True)
        subprocess.run(common+[str(p/"h.c"),str(p/"main.o"),
            *[str(ROOT/"bootloader/src"/n) for n in ("bcr.c","image_install.c","image_verify.c")],"-o",str(p/"h.exe")],check=True)
        failures=[]
        for scenario in range(9):
            result=subprocess.run([str(p/"h.exe"),str(scenario)],capture_output=True,text=True)
            if result.returncode: failures.append(result.stdout+result.stderr)
        assert not failures,"\n".join(failures)
    print("cold-start production C: PASS (9 recovery/fail-closed scenarios)")

if __name__ == "__main__": main()
