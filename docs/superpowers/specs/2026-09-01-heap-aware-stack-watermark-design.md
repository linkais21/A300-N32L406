# Heap-Aware Stack Watermark Design

## Problem

The application paints RAM from `_ebss` to the current stack pointer, then
scans from `_ebss` to estimate peak stack use. Newlib's heap also starts at
`_end == _ebss`. Any heap allocation therefore destroys the first watermark
word and is reported as full-stack use (`STK_FREE=0`), even when the heap and
stack remain separated.

## Design

Add a small `ram_watermark` module that measures three independent values from
the painted RAM interval:

- `heap_used`: current heap break minus the painted-region start.
- `stack_peak`: stack top minus the first non-pattern word at or above the
  current heap break.
- `free_gap`: untouched painted bytes between the current heap break and the
  stack low-water mark.

Expose the current heap break from `syscalls.c` through a read-only function.
The allocator policy, linker layout, heap size and stack size remain unchanged.
The scan begins at an aligned address at or above the live heap break, so heap
metadata cannot be mistaken for stack activity.

## Diagnostics

The health line will report:

```text
HEAP_USED=<bytes> STK_PEAK=<bytes> RAM_GAP=<bytes> RAM_AVAIL=<bytes> F=<0|1>
```

`F` latches when the measured heap-to-stack gap is below 4096 bytes or the
measurement bounds are invalid. The diagnostic contains only byte counts.

## Tests

A host C test uses a simulated painted RAM region and proves that:

1. Writing within the heap portion increases `heap_used` but not `stack_peak`.
2. Writing from the stack top downward increases `stack_peak` and reduces
   `free_gap` by the same amount.
3. Invalid or overlapping bounds return an invalid measurement.

Firmware validation includes the host test, existing stack observability test,
EC800M/JT808/Flash regressions, application build, release guard and RAM guard.
Physical HIL must confirm the health line reports a nonzero `RAM_GAP` during
registration/authentication.
