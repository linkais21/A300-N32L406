/* N32L406CBL7 application linker script
 * Flash: 104K @ 0x08006000 (after 24K Bootloader)
 * RAM:    24K @ 0x20000000  (SRAM1=16K + SRAM2=8K, per datasheet Table 1-1)
 * Stack: top of RAM = 0x20006000
 */

ENTRY(Reset_Handler)

PHDRS
{
  text PT_LOAD FLAGS(5);
  data PT_LOAD FLAGS(6);
}

_estack = 0x20006000;

/* Compatibility name: this reservation is also the _sbrk hard capacity. */
_Min_Heap_Size  = 0x400;
_Min_Stack_Size = 0x800;

MEMORY
{
  FLASH (rx)  : ORIGIN = 0x08006000, LENGTH = 104K
  RAM   (xrw) : ORIGIN = 0x20000000, LENGTH = 24K
}

SECTIONS
{
  .isr_vector :
  {
    . = ALIGN(4);
    KEEP(*(.isr_vector))
    . = ALIGN(4);
  } >FLASH :text

  .text :
  {
    . = ALIGN(4);
    *(.text)
    *(.text*)
    *(.glue_7)
    *(.glue_7t)
    *(.eh_frame)
    KEEP(*(.init))
    KEEP(*(.fini))
    . = ALIGN(4);
    _etext = .;
  } >FLASH :text

  .rodata :
  {
    . = ALIGN(4);
    *(.rodata)
    *(.rodata*)
    . = ALIGN(4);
  } >FLASH :text

  .ARM.extab : { *(.ARM.extab* .gnu.linkonce.armextab.*) } >FLASH :text
  .ARM :
  {
    __exidx_start = .;
    *(.ARM.exidx*)
    __exidx_end = .;
  } >FLASH :text

  .preinit_array :
  {
    PROVIDE_HIDDEN(__preinit_array_start = .);
    KEEP(*(.preinit_array*))
    PROVIDE_HIDDEN(__preinit_array_end = .);
  } >FLASH :text
  .init_array :
  {
    PROVIDE_HIDDEN(__init_array_start = .);
    KEEP(*(SORT(.init_array.*)))
    KEEP(*(.init_array*))
    PROVIDE_HIDDEN(__init_array_end = .);
  } >FLASH :text
  .fini_array :
  {
    PROVIDE_HIDDEN(__fini_array_start = .);
    KEEP(*(SORT(.fini_array.*)))
    KEEP(*(.fini_array*))
    PROVIDE_HIDDEN(__fini_array_end = .);
  } >FLASH :text

  _sidata = LOADADDR(.data);

  .data :
  {
    . = ALIGN(4);
    _sdata = .;
    *(.data)
    *(.data*)
    . = ALIGN(4);
    _edata = .;
  } >RAM AT> FLASH :data

  . = ALIGN(4);
  .bss (NOLOAD) :
  {
    _sbss = .;
    __bss_start__ = _sbss;
    *(.bss)
    *(.bss*)
    *(COMMON)
    . = ALIGN(4);
    _ebss = .;
    __bss_end__ = _ebss;
  } >RAM :NONE

  ._user_heap_stack (NOLOAD) :
  {
    . = ALIGN(4);
    PROVIDE(end = .);
    PROVIDE(_end = .);
    . = . + _Min_Heap_Size;
    _heap_limit = .;
    . = . + _Min_Stack_Size;
    . = ALIGN(4);
  } >RAM :NONE

  /DISCARD/ :
  {
    libc.a(*)
    libm.a(*)
    libgcc.a(*)
  }

  .ARM.attributes 0 : { *(.ARM.attributes) }
}

_app_load_end = LOADADDR(.data) + SIZEOF(.data);
ASSERT(_app_load_end <= 0x08020000, "application exceeds N32L406CBL7 Flash")
ASSERT(_heap_limit - _end == _Min_Heap_Size, "heap capacity mismatch")
ASSERT(_heap_limit <= _estack - _Min_Stack_Size, "heap overlaps minimum stack reservation")
