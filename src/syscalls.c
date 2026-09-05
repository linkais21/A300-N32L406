/* Newlib syscall stubs — required when libc is pulled in */
#include <sys/stat.h>
#include <errno.h>
#include <stdint.h>
#include "syscalls.h"

/* heap managed by linker symbols */
extern char _end;
extern uint32_t _estack;
static char *s_heap;

void *sys_heap_break(void)
{
    return s_heap != NULL ? s_heap : &_end;
}

void *_sbrk(int incr)
{
    char *prev;
    if (s_heap == NULL) s_heap = &_end;
    if ((s_heap + incr) > (char *)&_estack) { errno = ENOMEM; return (void *)-1; }
    prev = s_heap;
    s_heap += incr;
    return prev;
}

int _write(int fd, char *buf, int len) { (void)fd; (void)buf; return len; }
int _read(int fd, char *buf, int len)  { (void)fd; (void)buf; (void)len; return 0; }
int _close(int fd)                     { (void)fd; return -1; }
int _fstat(int fd, struct stat *st)    { (void)fd; st->st_mode = S_IFCHR; return 0; }
int _isatty(int fd)                    { (void)fd; return 1; }
int _lseek(int fd, int ptr, int dir)   { (void)fd; (void)ptr; (void)dir; return 0; }
int _getpid(void)                      { return 1; }
int _kill(int pid, int sig)            { (void)pid; (void)sig; errno = EINVAL; return -1; }
void _exit(int status)                 { (void)status; while(1); }
