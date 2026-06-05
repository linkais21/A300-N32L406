/* Newlib syscall stubs — required when libc is pulled in */
#include <sys/stat.h>
#include <errno.h>

/* heap managed by linker symbols */
extern char _end;
extern char _estack;

void *_sbrk(int incr)
{
    static char *heap = NULL;
    char *prev;
    if (!heap) heap = &_end;
    if ((heap + incr) > &_estack) { errno = ENOMEM; return (void *)-1; }
    prev  = heap;
    heap += incr;
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
