#ifndef SYSCALLS_H
#define SYSCALLS_H

/* Current break, not historical peak; allocation is main-context only.
 * _sbrk is confined to [_end, _heap_limit]. Out-of-range growth/shrink
 * returns (void *)-1 with ENOMEM and leaves this value unchanged. */
void *sys_heap_break(void);

#endif
