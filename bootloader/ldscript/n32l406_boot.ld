ENTRY(Reset_Handler)
MEMORY { FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 12K
         RAM (xrw) : ORIGIN = 0x20000000, LENGTH = 24K }
SECTIONS {
  .isr_vector : { KEEP(*(.isr_vector)) } > FLASH
  .text : { *(.text*) *(.rodata*) KEEP(*(.init)) KEEP(*(.fini)) } > FLASH
  .data : { *(.data*) } > RAM AT> FLASH
  .bss : { *(.bss*) *(COMMON) } > RAM
  /DISCARD/ : { libc.a(*) libm.a(*) libgcc.a(*) }
}
_boot_end = LOADADDR(.data) + SIZEOF(.data);
ASSERT(_boot_end - ORIGIN(FLASH) <= 0x2C00, "bootloader exceeds 11KB release limit")
