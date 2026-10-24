"""Real install_resume must validate the committed prefix before Trial."""
import shutil
import subprocess
import tempfile
from pathlib import Path

from test_boot_install_progress import HARNESS, ROOT


def main():
    source = HARNESS[:HARNESS.index("int main(void){")]
    source = source.replace("static unsigned fail_program;",
                            "static unsigned fail_program, bad_prefix, read_failure, corrupt_after_last_commit;")
    source = source.replace(
        "bool boot_int_flash_read(uint32_t a,void *p,uint32_t n){(void)a;memset(p,0x5a,n);return true;}",
        "bool boot_int_flash_read(uint32_t a,void *p,uint32_t n){"
        "if(a==APP_FLASH_BASE && read_failure)return false;memset(p,0x5a,n);"
        "if(a==APP_FLASH_BASE && (bad_prefix || (corrupt_after_last_commit && "
        "current.transaction_offset==current.transaction_length)))((uint8_t*)p)[0]^=1;return true;}")
    source += r'''
int main(int argc,char **argv){
    assert(argc==2);
    if(!strcmp(argv[1],"prefix")){
        reset(4096);bad_prefix=1;assert(!install_resume(4096));
    }else if(!strcmp(argv[1],"read")){
        reset(4096);read_failure=1;assert(!install_resume(4096));
    }else if(!strcmp(argv[1],"final")){
        reset(0);corrupt_after_last_commit=1;assert(!install_resume(0));
    }else if(!strcmp(argv[1],"complete")){
        reset(105208);bad_prefix=1;assert(!install_resume(105208));
    }else assert(0);
    assert(current.state==BCR_PENDING && !completed);
    /* Retry after the read fault/media repair validates even a final offset. */
    bad_prefix=read_failure=corrupt_after_last_commit=0;
    assert(install_resume(current.transaction_offset));
    assert(current.state==BCR_TRIAL && completed==1);
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix="boot_resume_integrity_") as td:
        p = Path(td)
        (p / "h.c").write_text(source, encoding="ascii")
        exe = p / "test.exe"
        subprocess.run([shutil.which("gcc") or shutil.which("clang"), "-std=c99", "-O1",
                        "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "bootloader/include"),
                        "-I", str(ROOT / "include"), str(p / "h.c"),
                        str(ROOT / "bootloader/src/image_install.c"), "-o", str(exe)],
                       check=True, timeout=60)
        failures = []
        for case in ("prefix", "read", "final", "complete"):
            run = subprocess.run([str(exe), case], capture_output=True, text=True, timeout=5)
            if run.returncode:
                failures.append(f"{case}: {run.stderr}")
            else:
                print(f"{case}: PASS")
        assert not failures, "\n".join(failures)


if __name__ == "__main__":
    main()
