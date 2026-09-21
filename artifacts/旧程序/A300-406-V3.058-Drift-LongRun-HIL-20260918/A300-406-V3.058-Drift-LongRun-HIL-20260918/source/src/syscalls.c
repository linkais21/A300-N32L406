/* Newlib syscall stubs — required when libc is pulled in */
#include <sys/stat.h>
#include <errno.h>
#include <stdint.h>
#include "syscalls.h"

/* heap managed by linker symbols */
extern char _end;
extern char _heap_limit;
static char *s_heap;

void *sys_heap_break(void)
{
    return s_heap != NULL ? s_heap : &_end;
}

__attribute__((used, externally_visible, noinline)) void *_sbrk(int incr)
{
    uintptr_t base = (uintptr_t)&_end;
    uintptr_t limit = (uintptr_t)&_heap_limit;
    uintptr_t prev = (uintptr_t)sys_heap_break();
    /* Compare distances before arithmetic: no out-of-range pointer arithmetic
     * or signed negation of INT_MIN. Allocation is main-context only. */
    uintptr_t amount = incr < 0 ? (uintptr_t)(-(incr + 1)) + 1U : (uintptr_t)incr;
    if (prev < base || prev > limit ||
        (incr < 0 ? amount > prev - base : amount > limit - prev)) {
        errno = ENOMEM;
        return (void *)-1;
    }
    s_heap = (char *)(incr < 0 ? prev - amount : prev + amount);
    return (void *)prev;
}

int _write(int fd, char *buf, int len) { (void)fd; (void)buf; return len; }
int _read(int fd, char *buf, int len)  { (void)fd; (void)buf; (void)len; return 0; }
int _close(int fd)                     { (void)fd; return -1; }
int _fstat(int fd, struct stat *st)    { (void)fd; st->st_mode = S_IFCHR; return 0; }
int _isatty(int fd)                    { (void)fd; return 1; }
int _lseek(int fd, int ptr, int dir)   { (void)fd; (void)ptr; (void)dir; return 0; }
int _getpid(void)                      { return 1; }
int _kill(int pid, int sig)            { (void)pid; (void)sig; errno = EINVAL; return -1; }

/* crt0 calls exit() after main returns.  Defining it in the application
 * prevents libc_nano's exit.o from being extracted solely for that call;
 * that object pulls in stdio cleanup state even though this firmware never
 * owns a hosted stdio stream. */
__attribute__((noreturn)) void _exit(int status)
{
    (void)status;
    while (1) {
    }
}

__attribute__((noreturn)) void exit(int status)
{
    _exit(status);
}
